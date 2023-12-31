"""
base classes to help glue Django forms to SQLAlchemy. Note that these are not
formal ABCs because this interferes with Django's metaclass structure.
however, they should always be subclassed, and attempts to instantiate these
classes will raise NotImplementedErrors.
"""
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
from viper_orchestrator.orchtypes import AppTable, JuncRow, JuncRule


class SAForm(forms.Form):
    """abstract-ish class for forms that help manage SQLAlchemy ORM objects"""

    def __init__(self, *args, **kwargs):
        if self.__class__.__name__ == 'SAForm':
            raise NotImplementedError("Only instantiate subclasses of SAForm.")
        super().__init__(*args, **kwargs)

    def _find_key(self, field):
        if hasattr(self, field):
            return getattr(self, field)
        elif self.pk_spec in self.base_fields.keys():
            return self.cleaned_data[field]
        raise NotImplementedError

    def get_pk(self):
        try:
            if isinstance(self.pk_spec, Mapping):
                return {k: self._find_key(v) for k, v in self.pk_spec.items()}
            return self._find_key(self.pk_spec)
        except (NotImplementedError, AttributeError):
            raise TypeError("self.pk_field not well-defined")
        except TypeError:
            raise TypeError("mangled pk_field definition")
        except KeyError:
            raise ValueError(
                f"defined pk attribute(s) {self.pk_spec} not found as "
                f"attribute(s) of self or member(s) of self.base_fields"
            )

    def get_row(
        self,
        session: Session,
        force_remake: bool = False,
        constructor_method: Optional[str] = None
    ) -> AppTable:
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
        # TODO: a convenient way to turn off extra_attrs associated with
        #  inactive fields (e.g., luminaires for a satisfied image request)
        #  -- this is basically to prevent weird UI bugs from breaking things
        data |= {attr: getattr(self, attr) for attr in self.extra_attrs}
        valid = set(dir(self.table_class))
        try:
            assert (key := self.get_pk()) is not None
            row = get_one(self.table_class, key, session=session)
            for k, v in keyfilter(lambda attr: attr in valid, data).items():
                setattr(row, k, v)
            self._row = row
        except (NoResultFound, AssertionError):
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

    _row: AppTable = None
    pk_spec: str = None
    table_class: type[AppTable] = None
    extra_attrs: tuple[str] = ()


class JunctionForm(SAForm):
    """
    abstract-ish class for forms that help manage SQLAlchemy many-to-many
    relationships (django's metaclass structure prevents us from making it an
    actual ABC)
    """

    def __init__(self, *args, **kwargs):
        if self.__class__.__name__ == 'JunctionForm':
            raise NotImplementedError(
                "Only instantiate subclasses of JunctionForm."
            )
        super().__init__(*args, **kwargs)
        # retrieved-from-database or ready-to-be-committed related objects,
        # organized by table and status
        self._relations = {k: {} for k in self.junc_rules.keys()}
        # lists of kwargs to be used for constructing or modifying related
        # objects
        self.junc_specs = {k: [] for k in self.junc_rules.keys()}

    def _check_relation_freshness(
        self, table: type[JuncRow], session: Session
    ):
        return (
            len(extant := self._relations[table].get('existing', [])) > 0
            and all(object_session(j) is session for j in extant)
        )

    @autosession
    def get_relations(
        self, table: type[JuncRow], *, session: Optional[Session] = None,
    ) -> dict[str, list[JuncRow]]:
        if self._check_relation_freshness(table, session) is True:
            return self._relations[table]
        junc_reference, referent = self.junc_rules[table]["pivot"]
        # noinspection PyTypeChecker
        exist_selector = select(table).where(
            getattr(table, junc_reference) == getattr(self, referent)
        )
        rel = self._relations[table]
        rel['existing'] = session.scalars(exist_selector).all()
        return rel['existing']

    @staticmethod
    def _check_row_against_specs(adict, junc_row, rules, specs):
        matches = []
        for i, s in specs.items():
            if (row := s.get(rules['junc_instance_spec_key'])) is None:
                return
            row_pk = getattr(row, pk(row))
            if row_pk == getattr(junc_row, rules['junc_pivot']):
                matches.append((i, s))
        # mark table entries not specified in this form for deletion,
        # unless the form is only for updates and/or single inserts
        if len(matches) == 0:
            # TODO, maybe: remove this special-case stuff
            if rules.get('update_only') or rules.get('never_delete'):
                return
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

    def _build_commit(self, table, *, session):
        rel = self._relations[table]
        if not all(
            object_session(r) is session for r in rel.get('existing', [])
        ):
            rel['existing'] = self.get_relations(table, session=session)
        specs = {i: s for i, s in enumerate(self.junc_specs[table])}
        rules = self.junc_rules[table]
        adict = defaultdict(list, {'existing': rel['existing']})
        for junc_row in adict['existing']:
            self._check_row_against_specs(adict, junc_row, rules, specs)
        # leftover specs are new table entries
        if len(specs) > 0:
            # TODO, maybe: remove this special-case stuff
            # for forms that are only used to update existing table entries
            if rules.get('update_only') is True:
                raise InvalidRequestError(
                    f"{self.__class__.__name__} cannot be used to construct "
                    f"new table entries."
                )
            # note: shouldn't need to set self_attr on existing junc rows
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
