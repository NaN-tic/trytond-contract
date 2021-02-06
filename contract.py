# The COPYRIGHT file at the top level of this repository contains
# the full copyright notices and license terms.
import datetime
from dateutil.relativedelta import relativedelta
from dateutil.rrule import rrule, DAILY, WEEKLY, MONTHLY, YEARLY
from decimal import Decimal
from itertools import groupby
from sql import Column, Null, Literal
from sql.conditionals import Case
from sql.aggregate import Max, Min, Sum

from trytond import backend
from trytond.model import (Workflow, ModelSQL, ModelView, Model, fields,
    sequence_ordered)
from trytond.pool import Pool, PoolMeta
from trytond.pyson import Eval, Bool, If
from trytond.transaction import Transaction
from trytond.tools import reduce_ids, grouped_slice
from trytond.wizard import Wizard, StateView, StateAction, Button
from trytond.modules.product import price_digits
from trytond.i18n import gettext
from trytond.exceptions import UserError

try:
    from trytond.modules.analytic_account import AnalyticMixin
except ModuleNotFoundError:
    AnalyticMixin = object


__all__ = ['ContractService', 'Contract', 'ContractLine',
    'ContractConsumption', 'CreateConsumptionsStart', 'CreateConsumptions',
    'AnalyticAccountEntry', 'AnalyticContractLine']

FREQS = [
    (None, ''),
    ('daily', 'Daily'),
    ('weekly', 'Weekly'),
    ('monthly', 'Monthly'),
    ('yearly', 'Yearly'),
    ]


class RRuleMixin(Model):
    freq = fields.Selection(FREQS, 'Frequency', sort=False)
    interval = fields.Integer('Interval', domain=[
            If(Bool(Eval('freq')),
                [('interval', '>', 0)], [])
            ],
        states={
            'required': Bool(Eval('freq')),
            }, depends=['freq'])

    def rrule_values(self):
        values = {}
        mappings = {
            'freq': {
                'daily': DAILY,
                'weekly': WEEKLY,
                'monthly': MONTHLY,
                'yearly': YEARLY,
                },
            }
        for field in ('freq', 'interval'):
            value = getattr(self, field)
            if not value:
                continue
            if field in mappings:
                if isinstance(mappings[field], str):
                    values[mappings[field]] = value
                else:
                    value = mappings[field][value]
            values[field] = value
        return values

    @property
    def rrule(self):
        'Returns rrule instance from current values'
        values = self.rrule_values()
        return rrule(**values)


class ContractService(ModelSQL, ModelView):
    'Contract Service'
    __name__ = 'contract.service'

    name = fields.Char('Name', required=True)
    product = fields.Many2One('product.product', 'Product', required=True,
        domain=[
            ('type', '=', 'service'),
            ])


_STATES = {
    'readonly': Eval('state') != 'draft',
    }
_DEPENDS = ['state']

CONTRACT_STATES = [
    ('draft', 'Draft'),
    ('confirmed', 'Confirmed'),
    ('cancelled', 'Cancelled'),
    ('finished', 'Finished'),
    ]


def todatetime(date):
    return datetime.datetime.combine(date, datetime.time(0, 0, 0))


class Contract(RRuleMixin, Workflow, ModelSQL, ModelView):
    'Contract'
    __name__ = 'contract'

    company = fields.Many2One('company.company', 'Company', required=True,
        states=_STATES, depends=_DEPENDS)
    currency = fields.Many2One('currency.currency', 'Currency', required=True,
        states=_STATES, depends=_DEPENDS)
    currency_digits = fields.Function(fields.Integer('Currency Digits'),
        'on_change_with_currency_digits')
    party = fields.Many2One('party.party', 'Party', required=True,
        states=_STATES, depends=_DEPENDS)
    number = fields.Char('Number', select=True, states=_STATES,
        depends=_DEPENDS)
    reference = fields.Char('Reference')
    start_date = fields.Function(fields.Date('Start Date'),
        'get_dates', searcher='search_dates')
    end_date = fields.Function(fields.Date('End Date'),
        'get_dates', searcher='search_dates')
    start_period_date = fields.Date('Start Period Date', required=True,
        states=_STATES, depends=_DEPENDS)
    first_invoice_date = fields.Date('First Invoice Date', required=True,
        states=_STATES, depends=_DEPENDS)
    lines = fields.One2Many('contract.line', 'contract', 'Lines',
        states={
            'readonly': ~Eval('state').in_(['draft', 'confirmed']),
            'required': Eval('state') == 'confirmed',
            },
        depends=['state'])
    state = fields.Selection(CONTRACT_STATES, 'State',
        required=True, readonly=True)
    payment_term = fields.Many2One('account.invoice.payment_term',
        'Payment Term')

    @classmethod
    def __setup__(cls):
        super(Contract, cls).__setup__()
        for field_name in ('freq', 'interval'):
            field = getattr(cls, field_name)
            field.states = _STATES.copy()
            field.states['required'] = True
            field.depends += _DEPENDS
        cls._transitions |= set((
                ('draft', 'confirmed'),
                ('draft', 'cancelled'),
                ('confirmed', 'draft'),
                ('confirmed', 'cancelled'),
                ('confirmed', 'finished'),
                ('cancelled', 'draft'),
                ('finished', 'draft'),
                ))
        cls._buttons.update({
                'draft': {
                    'invisible': ~Eval('state').in_(['cancelled', 'finished',
                            'confirmed']),
                    'icon': 'tryton-clear',
                    },
                'confirm': {
                    'invisible': Eval('state') != 'draft',
                    'icon': 'tryton-forward',
                    },
                'finish': {
                    'invisible': Eval('state') != 'confirmed',
                    'icon': 'tryton-forward',
                },
                'cancel': {
                    'invisible': ~Eval('state').in_(['draft', 'confirmed']),
                    'icon': 'tryton-cancel',
                    },
                })

    @classmethod
    def __register__(cls, module_name):
        Line = Pool().get('contract.line')
        TableHandler = backend.get('TableHandler')

        handler = TableHandler(cls, module_name)
        first_invoice_date_exist = handler.column_exist('first_invoice_date')

        if not handler.column_exist('number'):
            handler.column_rename('reference', 'number')

        super(Contract, cls).__register__(module_name)

        table = cls.__table__()
        line = Line.__table__()
        line_handler = TableHandler(Line, module_name)
        cursor = Transaction().connection.cursor()

        # Changed state field values
        cursor.execute(*table.update(columns=[table.state],
            values=['cancelled'], where=table.state == 'cancel'))
        cursor.execute(*table.update(columns=[table.state],
            values=['confirmed'], where=table.state == 'validated'))

        # Move first_invoice_date field from line into contract
        if (not first_invoice_date_exist
                and line_handler.column_exist('first_invoice_date')):
            query = table.update(
                [table.first_invoice_date],
                line.select(
                    Min(line.first_invoice_date),
                    where=table.id == line.contract,
                    group_by=line.contract))
            cursor.execute(*query)
            line_handler.drop_column('first_invoice_date')

    def _get_rec_name(self, name):
        rec_name = []
        if self.number:
            rec_name.append(self.number)
        if self.party:
            rec_name.append(self.party.rec_name)
        return rec_name

    def get_rec_name(self, name):
        rec_name = self._get_rec_name(name)
        return "/".join(rec_name)

    @classmethod
    def search_rec_name(cls, name, clause):
        return ['OR',
            ('number',) + tuple(clause[1:]),
            ('party.name',) + tuple(clause[1:]),
            ]

    @staticmethod
    def default_company():
        return Transaction().context.get('company')

    @staticmethod
    def default_currency():
        Company = Pool().get('company.company')
        if Transaction().context.get('company'):
            company = Company(Transaction().context['company'])
            return company.currency.id

    @staticmethod
    def default_state():
        return 'draft'

    @fields.depends('party')
    def on_change_party(self):
        self.payment_term = None
        if self.party:
            self.payment_term = self.party.customer_payment_term

    @fields.depends('currency')
    def on_change_with_currency_digits(self, name=None):
        if self.currency:
            return self.currency.digits
        return 2

    @classmethod
    def get_dates(cls, contracts, names):
        pool = Pool()
        ContractLine = pool.get('contract.line')
        cursor = Transaction().connection.cursor()
        line = ContractLine.__table__()
        result = {}
        contract_ids = [c.id for c in contracts]
        for name in names:
            if name not in ('start_date', 'end_date'):
                raise Exception('Bad argument')
            result[name] = dict((c, None) for c in contract_ids)
        for sub_ids in grouped_slice(contract_ids):
            where = reduce_ids(line.contract, sub_ids)
            for name in names:
                cursor.execute(*line.select(line.contract,
                        cls._compute_date_column(line, name),
                        where=where,
                        group_by=line.contract))
                for contract, value in cursor.fetchall():
                    # SQlite returns unicode for dates
                    if isinstance(value, str):
                        value = datetime.date(*[int(x) for x in
                                value.split('-')])
                    result[name][contract] = value
        return result

    @staticmethod
    def _compute_date_column(table, name):
        func = Min if name == 'start_date' else Max
        column = Column(table, name)
        sum_ = Sum(Case((column == Null, Literal(1)), else_=Literal(0)))
        # As fields can be null, return null if at least one of them is null
        return Case((sum_ >= Literal(1), Null), else_=func(column))

    @classmethod
    def search_dates(cls, name, clause):
        pool = Pool()
        ContractLine = pool.get('contract.line')
        line = ContractLine.__table__()
        Operator = fields.SQL_OPERATORS[clause[1]]
        query = line.select(line.contract, group_by=line.contract,
                having=Operator(cls._compute_date_column(line, name),
                clause[2]))
        return [('id', 'in', query)]

    @classmethod
    def set_number(cls, contracts):
        'Fill the number field with the contract sequence'
        pool = Pool()
        Sequence = pool.get('ir.sequence')
        Config = pool.get('contract.configuration')

        config = Config(1)
        to_write = []
        for contract in contracts:
            if contract.number:
                continue
            number = Sequence.get_id(config.contract_sequence.id)
            to_write.extend(([contract], {
                        'number': number,
                        }))
        if to_write:
            cls.write(*to_write)

    @classmethod
    def copy(cls, contracts, default=None):
        if default is None:
            default = {}
        default.setdefault('number', None)
        default.setdefault('end_date', None)
        return super(Contract, cls).copy(contracts, default=default)

    @classmethod
    @ModelView.button
    @Workflow.transition('draft')
    def draft(cls, contracts):
        Consumption = Pool().get('contract.consumption')
        consumptions = Consumption.search([
                ('contract', 'in', [x.id for x in contracts]),
                ])
        if consumptions:
            raise UserError(gettext('contract.cannot_draft',
                contract=consumptions[0].contract.rec_name))

    @classmethod
    @ModelView.button
    @Workflow.transition('confirmed')
    def confirm(cls, contracts):
        cls.set_number(contracts)
        for contract in contracts:
            for line in contract.lines:
                if not line.start_date:
                    raise UserError(gettext('contract.line_start_date_required',
                            line=line.rec_name,
                            contract=line.contract.rec_name))

    @classmethod
    @ModelView.button
    @Workflow.transition('cancelled')
    def cancel(cls, contracts):
        pass

    @classmethod
    @ModelView.button
    @Workflow.transition('finished')
    def finish(cls, contracts):
        for contract in contracts:
            for line in contract.lines:
                if not line.end_date:
                    raise UserError(gettext('contract.cannot_finish',
                            line=line.rec_name,
                            contract=line.contract.rec_name))

    def rrule_values(self):
        values = super(Contract, self).rrule_values()
        values['dtstart'] = todatetime(self.start_period_date)
        return values

    def get_invoice_date(self, last_invoice_date, start_period_date):
        last_invoice_date = todatetime(last_invoice_date)
        start_period_date = todatetime(start_period_date)
        r = rrule(self.rrule._freq, interval=self.rrule._interval,
            dtstart=last_invoice_date)
        date = last_invoice_date
        while date < start_period_date:
            date = r.after(date)
        return date.date()

    def get_start_period_date(self, start_date):
        r = rrule(self.rrule._freq, interval=self.rrule._interval,
            dtstart=self.start_period_date)
        date = r.before(todatetime(start_date), inc=True)
        if date:
            return date.date()
        return self.start_period_date

    def get_consumptions(self, limit_date=None):
        pool = Pool()
        Date = pool.get('ir.date')

        if limit_date is None:
            limit_date = Date.today()

        consumptions = []

        if not self.freq or not self.interval:
            return consumptions

        for line in self.lines:
            line_limit_date = limit_date
            if (line.end_date and line.last_consumption_date
                    and line.end_date <= line.last_consumption_date):
                continue
            if line.end_date and line.end_date < limit_date:
                line_limit_date = line.end_date
            start_period_date = self.get_start_period_date(line.start_date)

            last_consumption_date = line.last_consumption_date
            if last_consumption_date:
                last_consumption_date = todatetime(line.last_consumption_date)

            start = start_period_date
            if last_consumption_date:
                start = (last_consumption_date + relativedelta(days=+1)).date()

            last_invoice_date = line.last_consumption_invoice_date
            next_period = (self.rrule.after(todatetime(line_limit_date)) +
                relativedelta(days=+1))

            if line.end_date and next_period.date() < line.end_date:
                next_period = todatetime(line.end_date)

            rrule = self.rrule
            for date in rrule.between(todatetime(start), next_period,
                    inc=True):
                start_period = date.date()

                last_invoice_date = (last_invoice_date
                    or line.contract.first_invoice_date)

                invoice_date = self.get_invoice_date(last_invoice_date,
                        start_period)

                if (start_period > line_limit_date):
                    break
                end_period = rrule.after(date).date() - relativedelta(days=1)

                start = start_period
                if line.start_date > start:
                    start = line.start_date
                end = end_period
                if line.end_date and line.end_date <= end:
                    end = line.end_date
                if not (end >= start):
                    continue

                consumptions.append(line.get_consumption(start, end,
                        invoice_date, start_period, end_period))
                last_invoice_date = invoice_date
        return consumptions

    @classmethod
    def consume(cls, contracts, date=None):
        'Consume the contracts until date'
        ContractConsumption = Pool().get('contract.consumption')

        to_create = []
        for contract in contracts:
            to_create += contract.get_consumptions(date)

        return ContractConsumption.create([x._save_values for x in to_create])


class ContractLine(sequence_ordered(), ModelSQL, ModelView):
    'Contract Line'
    __name__ = 'contract.line'

    contract = fields.Many2One('contract', 'Contract', required=True,
        ondelete='CASCADE')
    contract_state = fields.Function(fields.Selection(CONTRACT_STATES,
            'Contract State'), 'get_contract_state',
        searcher='search_contract_state')
    service = fields.Many2One('contract.service', 'Service', required=True,
        states={
            'readonly': Eval('contract_state') == 'confirmed',
            })
    start_date = fields.Date('Start Date',
        states={
            'readonly': Eval('contract_state') == 'confirmed',
            'required': Eval('contract_state') == 'confirmed',
            },
        domain=[
            If(Bool(Eval('end_date')),
                ('start_date', '<=', Eval('end_date', None)),
                ()),
            ],
        depends=['end_date', 'contract_state'])
    end_date = fields.Date('End Date',
        states={
            'required': Eval('contract_state') == 'finished',
            },
        domain=[
            If(Bool(Eval('end_date')),
                ('end_date', '>=', Eval('start_date', None)),
                ()),
            ],
        depends=['start_date', 'contract_state'])
    description = fields.Text('Description', required=True)
    unit_price = fields.Numeric('Unit Price', digits=price_digits,
        required=True)
    last_consumption_date = fields.Function(fields.Date(
            'Last Consumption Date'), 'get_last_consumption_date',
            searcher='search_last_consumption_dates')
    last_consumption_invoice_date = fields.Function(fields.Date(
            'Last Invoice Date'), 'get_last_consumption_date',
            searcher='search_last_consumption_dates')
    consumptions = fields.One2Many('contract.consumption', 'contract_line',
        'Consumptions', readonly=True)

    @classmethod
    def __setup__(cls):
        super(ContractLine, cls).__setup__()
        cls._order.insert(0, ('contract', 'ASC'))

    @classmethod
    def __register__(cls, module_name):
        TableHandler = backend.get('TableHandler')
        table = TableHandler(cls, module_name)
        super(ContractLine, cls).__register__(module_name)

        # start_date not null
        table.not_null_action('start_date', 'remove')

    def get_rec_name(self, name):
        rec_name = self.contract.rec_name
        if self.service:
            rec_name = '%s (%s)' % (self.service.rec_name, rec_name)
        return rec_name

    @classmethod
    def search_rec_name(cls, name, clause):
        return ['OR',
            ('contract.rec_name',) + tuple(clause[1:]),
            ('service.rec_name',) + tuple(clause[1:]),
            ]

    def get_contract_state(self, name):
        return self.contract and self.contract.state or 'draft'

    @classmethod
    def search_contract_state(cls, name, clause):
        return [
            ('contract.state',) + tuple(clause[1:]),
            ]

    @fields.depends('service', 'unit_price', 'description')
    def on_change_service(self):
        if self.service:
            self.name = self.service.rec_name
            if not self.unit_price:
                self.unit_price = self.service.product.list_price
            if not self.description:
                self.description = self.service.product.rec_name

    @classmethod
    def get_last_consumption_date(cls, lines, name):
        pool = Pool()
        Consumption = pool.get('contract.consumption')
        table = Consumption.__table__()
        cursor = Transaction().connection.cursor()

        if name == 'last_consumption_invoice_date':
            consumption_date = table.invoice_date
        else:
            consumption_date = table.end_period_date

        line_ids = [l.id for l in lines]
        values = dict.fromkeys(line_ids, None)
        cursor.execute(*table.select(table.contract_line,
                Max(consumption_date),
                where=reduce_ids(table.contract_line, line_ids),
                group_by=table.contract_line))
        values.update(dict(cursor.fetchall()))
        if backend.name() == 'sqlite':
            for id, value in values.items():
                if value is not None:
                    values[id] = datetime.date(*[int(x) for x in value.split('-', 2)])
        return values

    @classmethod
    def get_last_consumption_invoice_date(cls, lines, name):
        pool = Pool()
        Consumption = pool.get('contract.consumption')
        table = Consumption.__table__()
        cursor = Transaction().connection.cursor()

        line_ids = [l.id for l in lines]
        values = dict.fromkeys(line_ids, None)
        cursor.execute(*table.select(table.contract_line,
                Max(table.invoice_date),
                where=reduce_ids(table.contract_line, line_ids),
                group_by=table.contract_line))
        values.update(dict(cursor.fetchall()))
        return values

    @classmethod
    def search_last_consumption_dates(cls, name, clause):
        Consumption = Pool().get('contract.consumption')
        consumption = Consumption.__table__()

        res = {
            'last_consumption_date': 'end_period_date',
            'last_consumption_invoice_date': 'invoice_date',
            }
        Operator = fields.SQL_OPERATORS[clause[1]]
        column = Column(consumption, res[clause[0]])
        query = consumption.select(consumption.contract_line,
            group_by=(consumption.contract_line),
            having=Operator(Max(column), clause[2]))

        return [('id', 'in', query)]

    def get_consumption(self, start_date, end_date, invoice_date, start_period,
            finish_period):
        'Returns the consumption for date date'
        pool = Pool()
        Consumption = pool.get('contract.consumption')
        consumption = Consumption()
        consumption.contract_line = self
        consumption.start_date = start_date
        consumption.end_date = end_date
        consumption.init_period_date = start_period
        consumption.end_period_date = finish_period
        consumption.invoice_date = invoice_date
        return consumption

    @classmethod
    def delete(cls, lines):
        for line in lines:
            if line.contract_state != 'draft':
                raise UserError(gettext('contract.cannot_delete',
                        line=line.rec_name,
                        contract=line.contract.rec_name))
        super(ContractLine, cls).delete(lines)

    @classmethod
    def copy(cls, lines, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('consumptions')
        return super(ContractLine, cls).copy(lines, default=default)


class AnalyticContractLine(AnalyticMixin, metaclass=PoolMeta):
    __name__ = 'contract.line'


class AnalyticAccountEntry(metaclass=PoolMeta):
    __name__ = 'analytic.account.entry'

    @classmethod
    def _get_origin(cls):
        origins = super()._get_origin()
        origins.append('contract.line')
        return origins


class ContractConsumption(ModelSQL, ModelView):
    'Contract Consumption'
    __name__ = 'contract.consumption'

    contract_line = fields.Many2One('contract.line', 'Contract Line',
        required=True)
    init_period_date = fields.Date('Start Period Date', required=True,
        domain=[
            ('init_period_date', '<=', Eval('end_period_date', None)),
            ],
        depends=['end_period_date'])
    end_period_date = fields.Date('Finish Period Date', required=True,
        domain=[
            ('end_period_date', '>=', Eval('init_period_date', None)),
            ],
        depends=['init_period_date'])
    start_date = fields.Date('Start Date', required=True,
        domain=[
            ('start_date', '<=', Eval('end_date', None)),
            ],
        depends=['end_date'])
    end_date = fields.Date('End Date', required=True,
        domain=[
            ('end_date', '>=', Eval('start_date', None)),
            ],
        depends=['start_date'])
    invoice_date = fields.Date('Invoice Date', required=True)
    invoice_lines = fields.One2Many('account.invoice.line', 'origin',
        'Invoice Lines', readonly=True)
    credit_lines = fields.Function(fields.One2Many('account.invoice.line',
            None, 'Credit Lines',
            states={
                'invisible': ~Bool(Eval('credit_lines')),
                }),
        'get_credit_lines')
    contract = fields.Function(fields.Many2One('contract',
        'Contract'), 'get_contract', searcher='search_contract')

    @classmethod
    def __setup__(cls):
        super(ContractConsumption, cls).__setup__()
        cls._buttons.update({
                'generate_invoice': {
                    'icon': 'tryton-go-next',
                    },
                })

    def get_credit_lines(self, name):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        return [x.id for x in InvoiceLine.search([
                    ('origin.id', 'in', [l.id for l in self.invoice_lines],
                        'account.invoice.line')])]

    def get_contract(self, name=None):
        return self.contract_line.contract.id

    @classmethod
    def search_contract(cls, name, clause):
        return [('contract_line.contract',) + tuple(clause[1:])]

    def _get_tax_rule_pattern(self):
        '''
        Get tax rule pattern
        '''
        return {}

    def _get_start_end_date(self):
        pool = Pool()
        Lang = pool.get('ir.lang')
        if self.contract.party.lang:
            lang = self.contract.party.lang
        else:
            lang = Lang.get()
        start = lang.strftime(self.start_date)
        end = lang.strftime(self.end_date)
        return start, end

    def get_invoice_line(self):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        AccountConfiguration = pool.get('account.configuration')
        Module = pool.get('ir.module')
        analytic_invoice_installed = Module.search([
              ('name', '=', 'analytic_invoice'),
              ('state', '=', 'activated'),
                ], limit=1)
        if analytic_invoice_installed:
            AnalyticAccountEntry = pool.get('analytic.account.entry')
        account_config = AccountConfiguration(1)
        if (self.invoice_lines and
                not Transaction().context.get('force_reinvoice', False)):
            return
        invoice_line = InvoiceLine()
        invoice_line.type = 'line'
        invoice_line.origin = self
        invoice_line.company = self.contract_line.contract.company
        invoice_line.currency = self.contract_line.contract.currency
        invoice_line.sequence = self.contract_line.sequence
        invoice_line.product = None
        if self.contract_line.service:
            invoice_line.product = self.contract_line.service.product
        start_date, end_date = self._get_start_end_date()
        invoice_line.description = '[%(start)s - %(end)s] %(name)s' % {
            'start': start_date,
            'end': end_date,
            'name': self.contract_line.description,
            }
        invoice_line.quantity = 1
        if self.end_period_date == self.init_period_date:
            rate = Decimal(0)
        else:
            # Compute quantity based on dates
            # We add 1 day to end_date and end_period date to correctly
            #   calculate periods. for example:
            #   (31-01-2015 - 01-01-2015) = 30 days + 1
            rate = Decimal((self.end_date + datetime.timedelta(days=1)
                    - self.start_date).total_seconds() /
                (self.end_period_date + datetime.timedelta(days=1) -
                    self.init_period_date).total_seconds())
        unit_price = self.contract_line.unit_price * rate
        digits = invoice_line.__class__.unit_price.digits
        unit_price = unit_price.quantize(Decimal(str(10 ** -digits[1])))
        invoice_line.unit_price = unit_price
        invoice_line.party = self.contract_line.contract.party
        taxes = []
        if invoice_line.product:
            invoice_line.unit = invoice_line.product.default_uom
            party = invoice_line.party
            pattern = self._get_tax_rule_pattern()
            for tax in invoice_line.product.customer_taxes_used:
                if party.customer_tax_rule:
                    tax_ids = party.customer_tax_rule.apply(tax, pattern)
                    if tax_ids:
                        taxes.extend(tax_ids)
                    continue
                taxes.append(tax.id)
            if party.customer_tax_rule:
                tax_ids = party.customer_tax_rule.apply(None, pattern)
                if tax_ids:
                    taxes.extend(tax_ids)
            invoice_line.account = invoice_line.product.account_revenue_used
            if not invoice_line.account:
                raise UserError(gettext(
                    'contract.missing_account_revenue',
                        contract_line=self.contract_line.rec_name,
                        product=invoice_line.product.rec_name))
        else:
            invoice_line.unit = None
            for name in ['default_product_account_revenue',
                    'default_category_account_revenue']:
                invoice_line.account = account_config.get_multivalue(name)
                if invoice_line.account:
                    break
            if not invoice_line.account:
                raise UserError(gettext(
                    'contract.missing_account_revenue_property',
                        contract_line=self.contract_line.rec_name))

        invoice_line.taxes = taxes
        invoice_line.invoice_type = 'out'
        if analytic_invoice_installed:
            invoice_line.analytic_accounts = AnalyticAccountEntry.copy(
                self.contract_line.analytic_accounts, default={
                    'origin': invoice_line.id})

        return invoice_line

    def get_amount_to_invoice(self):
        Uom = Pool().get('product.uom')

        uom, = Uom.search([('name', '=', 'Unit')])

        quantity = ((self.end_date - self.start_date).total_seconds() /
            (self.end_period_date - self.init_period_date).total_seconds())

        if self.contract_line and self.contract_line.service and \
                self.contract_line.service.product:
            uom = self.contract_line.service.product.default_uom
        qty = uom.round(quantity)
        return Decimal(str(qty)) * self.contract_line.unit_price

    @classmethod
    def _group_invoice_key(cls, line):
        '''
        The key to group invoice_lines by Invoice

        line is a tuple of consumption id and invoice line
        '''
        consumption, invoice_line = line
        grouping = [
            ('party', invoice_line.party),
            ('company', invoice_line.company),
            ('currency', invoice_line.currency),
            ('type', invoice_line.invoice_type),
            ('invoice_date', consumption.invoice_date),
            ('payment_term', consumption.contract.payment_term),
            ]
        if invoice_line.party.contract_grouping_method is None:
            grouping.append(('contract', consumption.contract_line.contract))
        return grouping

    @classmethod
    def _get_invoice(cls, keys):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        Config = pool.get('contract.configuration')

        config = Config(1)
        journal = config.journal
        if not journal:
            raise UserError(gettext('contract.missing_journal'))

        values = dict(keys)
        values['invoice_address'] = values['party'].address_get('invoice')
        invoice = Invoice(**values)
        invoice.on_change_party()
        invoice.journal = journal
        invoice.payment_term = values['payment_term']
        if values.get('contract'):
            contract = values['contract']
            invoice.reference = contract.reference
        return invoice

    @classmethod
    @ModelView.button
    def generate_invoice(cls, consumptions):
        cls._invoice(consumptions)

    @classmethod
    def _invoice(cls, consumptions):
        pool = Pool()
        Invoice = pool.get('account.invoice')
        lines = {}
        for consumption in consumptions:
            line = consumption.get_invoice_line()
            if line:
                lines[consumption] = line

        if not lines:
            return []
        lines = sorted(lines.items(), key=cls._group_invoice_key)

        invoices = []
        for key, grouped_lines in groupby(lines, key=cls._group_invoice_key):
            invoice = cls._get_invoice(key)
            invoice.lines = (list(getattr(invoice, 'lines', [])) +
                list(x[1] for x in grouped_lines))
            invoices.append(invoice)

        invoices = Invoice.create([x._save_values for x in invoices])
        Invoice.update_taxes(invoices)
        return invoices

    @classmethod
    def delete(cls, consumptions):
        pool = Pool()
        InvoiceLine = pool.get('account.invoice.line')
        lines = InvoiceLine.search([
                ('origin', 'in', [str(c) for c in consumptions])
                ], limit=1)
        if lines:
            line, = lines
            raise UserError(gettext(
                'contract.delete_invoiced_consumption',
                consumption=line.origin.rec_name))
        super(ContractConsumption, cls).delete(consumptions)

    @classmethod
    def copy(cls, consumptions, default=None):
        if default is None:
            default = {}
        default = default.copy()
        default.setdefault('invoice_lines')
        default.setdefault('credit_lines')
        return super(ContractConsumption, cls).copy(
            consumptions, default=default)


class CreateConsumptionsStart(ModelView):
    'Create Consumptions Start'
    __name__ = 'contract.create_consumptions.start'
    date = fields.Date('Date')

    @staticmethod
    def default_date():
        Date = Pool().get('ir.date')
        return Date.today()


class CreateConsumptions(Wizard):
    'Create Consumptions'
    __name__ = 'contract.create_consumptions'
    start = StateView('contract.create_consumptions.start',
        'contract.create_consumptions_start_view_form', [
            Button('Cancel', 'end', 'tryton-cancel'),
            Button('OK', 'create_consumptions', 'tryton-ok', True),
            ])
    create_consumptions = StateAction(
            'contract.act_contract_consumption')

    def do_create_consumptions(self, action):
        pool = Pool()
        Contract = pool.get('contract')
        contracts = Contract.search([
                ('state', 'in', ['confirmed', 'finished']),
                ])
        consumptions = Contract.consume(contracts, self.start.date)
        data = {'res_id': [c.id for c in consumptions]}
        if len(consumptions) == 1:
            action['views'].reverse()
        return action, data
