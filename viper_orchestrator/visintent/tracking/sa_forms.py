"""base classes to help glue Django forms to SQLAlchemy."""
from collections import defaultdict
from functools import cached_property
from typing import Mapping, Optional

from cytoolz import keyfilter
from django import forms
from sqlalchemy import select
from sqlalchemy.exc import NoResultFound, InvalidRequestError
from sqlalchemy.orm import Session, object_session

from viper_orchestrator.db.session import autosession
from viper_orchestrator.db.table_utils import get_one, pk
from viper_orchestrator.utils import get_argnames
from viper_orchestrator.typing import AppRule, JuncRow, JuncRule


class SAForm(forms.Form):
    """abstract-ish class for forms that help manage SQLAlchemy ORM objects"""

    def get_row(
        self,
        session: Session,
        force_remake: bool = False,
        constructor_method: Optional[str] = None
    ) -> AppRule:
        """
        NOTE: autosession is not enabled for this function because an ad-hoc 
        Session will cause the function to return detached DeclarativeBase
        instances, which will cause hard-to-diagnose bugs in many anticipated
        workflows that incorporate this function (in particular, those that 
        will touch any relations to other tables.)
        """
        if (
            (self._row is not None)
            and object_session(self._row) is session
            and (force_remake is False)
        ):
            return self._row
        data = {k: v for k, v in self.cleaned_data.items()}
        data |= {attr: getattr(self, attr) for attr in self.extra_attrs}
        try:
            if hasattr(self, self.pk_field):
                ref = getattr(self, self.pk_field)
            elif self.pk_field in self.base_fields.keys():
                ref = self.cleaned_data[self.pk_field]
            else:
                raise NotImplementedError
        except (NotImplementedError, AttributeError):
            raise TypeError("self.pivot not well-defined")
        except TypeError:
            raise TypeError("mangled pivot definition")
        except KeyError:
            raise ValueError(
                f"defined pk attribute {self.pk_field} not an attribute of "
                f"self or a member of self.base_fields"
            )
        try:
            row = get_one(
                self.table_class,
                getattr(self, self.pk_field),
                session=session
            )
            for k, v in data.items():
                setattr(row, k, v)
            self._row = row
        except NoResultFound:
            data[self.pk_field] = ref
            valid = set(dir(self.table_class))
            if constructor_method is None:
                constructor = self.table_class
            else:
                constructor = getattr(self.table_class, constructor_method)
                valid.update(get_argnames(constructor))
            self._row = constructor(
                **(keyfilter(lambda attr: attr in valid, data))
            )
        return self._row

    @autosession
    def commit(
        self,
        session: Optional[Session] = None,
        force_remake: bool = False,
        constructor_method: Optional[str] = None
    ):
        """
        constructor_method: if present, should be the name of a constructor
            method of self.table_class; defaults to self.table_class.__init__
        """
        session.add(self.get_row(session, force_remake, constructor_method))
        session.commit()

    _row: AppRule = None
    pk_field: str
    table_class: type[AppRule]
    extra_attrs: tuple[str] = ()


class JunctionForm(SAForm):
    """
    abstract-ish class for forms that help manage SQLAlchemy many-to-many
    relationships (django's metaclass structure prevents us from making it an
    actual ABC)
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # retrieved-from-database or ready-to-be-committed related objects,
        # organized by table and status
        self._relations = {k: {} for k in self.junc_rules.keys()}
        # lists of kwargs to be used for constructing or modifying related
        # objects
        self.junc_specs = {k: [] for k in self.junc_rules.keys()}

    @autosession
    def get_relations(
        self, table: type[JuncRow], *, session: Optional[Session] = None,
    ) -> dict[str, list[JuncRow]]:
        rel = self._relations[table]
        if len(extant := rel.get('existing', [])) > 0:
            if all(object_session(j) is session for j in extant):
                return rel
        rules = self.junc_rules[table]
        junc_reference, referent = rules["pivot"]
        # noinspection PyTypeChecker
        exist_selector = select(table).where(
            getattr(table, junc_reference) == getattr(self, referent)
        )
        rel['existing'] = session.scalars(exist_selector).all()
        return rel['existing']

    def _build_commit(self, table, *, session):
        rel = self._relations[table]
        if not all(object_session(r) is session for r in rel['existing']):
            rel['existing'] = self.get_relations(table, session=session)
        specs = {i: s for i, s in enumerate(self.junc_specs[table])}
        rules = self.junc_rules[table]
        adict = defaultdict(list, {'existing': rel['existing']})
        for junc_row in adict['existing']:
            matches = []
            for i, s in specs.items():
                if (row := s.get('junc_pivot')) is None:
                    continue
                pk_field = pk(row)
                if getattr(row, pk_field) == getattr(junc_row, pk_field):
                    matches.append(s)
            # mark table entries not specified in this form for deletion
            if len(matches) == 0:
                adict['missing'].append(junc_row)
            elif len(matches) > 1:
                raise InvalidRequestError(
                    "Only one matching row is expected here; table "
                    "contents appear invalid"
                )
            # update fields of existing, specified table entries
            else:
                for attr, val in matches[0][1].items():
                    setattr(junc_row, attr, val)
                adict['present'].append(junc_row)
                specs.pop(matches[0][0])
        # leftover specs are new table entries
        if len(specs) > 0:
            # shouldn't need to define self_attr on existing junc table rows
            row = self.get_row(session)
            for s in specs.values():
                junc_row = table()
                # TODO, maybe: sloppy?
                for attr, val in s.items():
                    setattr(junc_row, attr, val)
                setattr(junc_row, rules["self_attr"], row)
                adict['new'].append(junc_row)
        self._relations[table] = dict(adict)
        return self._relations[table]

    @autosession
    def commit(
        self,
        session: Optional[Session] = None,
        force_remake: bool = False,
        constructor_method: Optional[str] = None
    ):
        removed = []
        for table in self.junc_rules.keys():
            self.get_relations(table, session=session)
            related = self._build_commit(table, session=session)
            # already-present rows (under the key 'present') are already
            # attached to session
            session.add_all(related.get('new', []))
            removed += related.get('missing', [])
        row = self.get_row(session, force_remake, constructor_method)
        session.add(row)
        for r in removed:
            session.delete(r)
        session.commit()

    @autosession
    def _populate_junc_fields(self, *, session: Optional[Session] = None):
        for table, rules in self.junc_rules.items():
            existing = self.get_relations(table, session=session)
            if len(existing) != 0:
                rules["populator"](existing)

    @cached_property
    def associated_form_fields(self):
        return set(
            filter(
                None,
                (r.get("form_field") for r in self.junc_rules.values()),
            )
        )

    _relations: dict[type[JuncRow, dict[str, list[JuncRow]]]]
    junc_rules: Mapping[type[JuncRow], JuncRule]
    junc_specs: dict[type[JuncRow], list[dict]]
