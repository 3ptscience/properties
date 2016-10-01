from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from builtins import super
from builtins import range
from functools import wraps
from future.utils import with_metaclass
import json
from six import string_types

from . import exceptions


_REGISTRY = {}


class _PropertyMetaClass(type):
    """metaclass that sets up behavior of properties within PropertyClass"""
    def __new__(cls, name, bases, attrs):
        _properties = {}
        for base in reversed(bases):
            for base_prop in getattr(base, '_properties', {}):
                _properties[base_prop] = base._properties[base_prop]

        keys = [k for k in attrs]
        for attr in keys:
            prop = attrs[attr]
            if isinstance(prop, Property):
                assert not attr.startswith('_'), \
                    "Cannot start a property name with '_'."
                prop.name = attr
                prop.class_name = name
                prop._set_property_meta(attrs, _properties)

        attrs['_properties'] = _properties
        attrs['_class_name'] = name

        # The doc string
        doc_str = attrs.get('__doc__', '')
        required = {key: value for key, value in _properties.items()
                    if value.required}
        optional = {key: value for key, value in _properties.items()
                    if not value.required}
        if required:
            doc_str += '\n\nRequired:\n\n' + '\n'.join(
                (required[key].sphinx for key in required))
        if optional:
            doc_str += '\n\nOptional:\n\n' + '\n'.join(
                (optional[key].sphinx for key in optional))
        attrs['__doc__'] = doc_str.strip()

        # Figure out what is the set of properties that is exposed.
        _exposed = []
        for k, p in _properties.items():
            _exposed += p._exposed
        attrs['_exposed'] = set(_exposed)

        new_class = super().__new__(cls, name, bases, attrs)
        _REGISTRY[name] = new_class

        return new_class


class PropertyClass(with_metaclass(_PropertyMetaClass, object)):
    """class properties.PropertyClass

    PropertyClasses are set up to contain property classes
    """

    _sphinx_prefix = 'properties.base'

    def __init__(self, **kwargs):
        self._dirty_props = set()
        self.set(**kwargs)

    @validator
    def validate(self):
        return True

    @property
    def _dirty(self):
        if getattr(self, '_inside_dirty', False):
            return set()
        dirty_pointers = set()
        self._inside_dirty = True
        keys = [k for k in self._properties if
                isinstance(self._properties[k], Pointer)]
        for key in keys:
            if self._properties[key].repeated:
                for prop in getattr(self, key):
                    if len(prop._dirty) > 0:
                        dirty_pointers.add(key)
            else:
                prop = getattr(self, '_p_' + key, None)
                if prop is not None and len(prop._dirty) > 0:
                    dirty_pointers.add(key)
        self._inside_dirty = False
        return self._dirty_props.union(dirty_pointers)

    def _mark_dirty(self, name):
        assert name in self._properties, \
            '{name} not in properties'.format(name=name)
        self._dirty_props.add(name)

    def _mark_clean(self, recurse=True):
        self._dirty_props = set()
        if not recurse or getattr(self, '_inside_clean', False):
            return
        self._inside_clean = True
        keys = [k for k in self._dirty if
                isinstance(self._properties[k], Pointer)]
        for key in keys:
            if self._properties[key].repeated:
                for prop in getattr(self, key):
                    prop._mark_clean()
            else:
                getattr(self, key)._mark_clean()
        self._inside_clean = False

    def _on_property_change(self, key, pre, post):
        pass

    def set(self, **kwargs):
        errors = []
        for key in kwargs:
            if key[0] == '_':
                errors += ['"{}": Cannot set private properties.'.format(key)]
            elif key not in self._exposed:
                errors += ['"{}": Property name not found.'.format(key)]
        if len(errors) > 0:
            raise KeyError(
                'Property Class could not set keys for: \n    {}'.format(
                    '\n    '.join(errors)))
        for key in kwargs:
            setattr(self, key, kwargs[key])


class Pointer(Property):
    """class properties.Pointer

    Pointers are properties that contain a PropertyClass. They allow
    one PropertyClass to be a property of another PropertyClass.
    """

    _resolved = True
    _sphinx_prefix = 'properties.base'

    def __init__(self, doc, auto_create=True, **kwargs):
        self.auto_create = auto_create
        super().__init__(doc, **kwargs)

    @classmethod
    def resolve(cls, resolved=True):
        """classmethod properties.Pointer.resolve

        resolving the pointers is necessary when pointer ptype contains
        a PropertyClass name, rather than the PropertyClass itself
        """
        cls._resolved = resolved

    @property
    def doc(self):
        if getattr(self, '_doc', None) is None:
            if self.ptype is None:
                self._doc = self._base_doc
            elif isinstance(self.ptype, (list, tuple)):
                self._doc = self._base_doc + ', Pointer to :class:`.'
                self._doc += (self.ptype[0] if isinstance(
                    self.ptype[0], string_types) else self.ptype[0].__name__)
                self._doc += '` (default)'
                for s in self.ptype[1:]:
                    self._doc += ', :class:`.' + (s if isinstance(
                        s, string_types) else s.__name__) + '`'
            else:
                self._doc = self._base_doc + ', Pointer to :class:`.'
                self._doc += (self.ptype if isinstance(
                    self.ptype, string_types) else self.ptype.__name__) + '`'
        return self._doc

    @property
    def ptype(self):
        """Type of PropertyClass the Pointer points to"""
        if self._resolved:
            ptype = getattr(self, '_ptype', None)
            if isinstance(ptype, (list, tuple)):
                self._ptype = [
                    _REGISTRY[p] if isinstance(p, string_types) else p
                    for p in ptype
                ]
            elif isinstance(ptype, string_types):
                self._ptype = _REGISTRY[ptype]
        return getattr(self, '_ptype', None)

    @ptype.setter
    def ptype(self, val):
        if isinstance(val, (list, tuple)):
            for v in val:
                if isinstance(v, string_types):
                    self.resolve(False)
                elif not issubclass(v, PropertyClass):
                    raise AttributeError(
                        'ptype must be a list of PropertyClasses')
        elif isinstance(val, string_types):
            self.resolve(False)
        elif not issubclass(val, PropertyClass):
            raise AttributeError('ptype must be a list or a PropertyClass')
        self._ptype = val

    @property
    def expose(self):
        return getattr(self, '_expose', [])

    @expose.setter
    def expose(self, val):
        if not isinstance(val, list):
            raise AttributeError('exposed values must be lists')
        for v in val:
            if not isinstance(v, string_types):
                raise AttributeError('exposed values must be lists of strings')
        self._expose = val

    @property
    def _exposed(self):
        """The properties that are exposed on the class."""
        return [self.name] + self.expose

    @property
    def sphinx(self):
        """Sphinx documentation for the property"""
        if not isinstance(self.ptype, (list, tuple)):
            cname = (self.ptype if isinstance(self.ptype, string_types)
                     else self.ptype.__name__)
            return ':param {}: {}\n:type {}: :class:`.{}`'.format(
                self.name, self.doc, self.name, cname)
        cname = [p if isinstance(p, string_types) else p.__name__
                 for p in self.ptype]
        cnamestr = ':class:`.{}`'.format('`, :class:`.'.join(cname))
        return ':param {}: {}\n:type {}: {}'.format(
            self.name, self.doc, self.name, cnamestr)

    @property
    def default(self):
        if self.repeated:
            return []
        if not self.auto_create:
            return None
        if not self._resolved:
            raise AttributeError(
                "Pointers are must be resolved with "
                "'Pointers.resolve()' before proceeding")
        if isinstance(self.ptype, (list, tuple)):
            pdef = self.ptype[0]
        else:
            pdef = self.ptype
        try:
            return pdef()
        except TypeError:
            raise AttributeError(
                "Cannot set default property of class {name}. "
                "Set 'auto_create=False' for pointers of this type".format(
                    name=pdef.__name__))

    def validate(self, scope):
        """validate the pointer"""
        super().validate(scope)
        P = getattr(scope, self.name)
        if not self.required and (P is None or P == []):
            return True
        if self.repeated:
            for p in P:
                p.validate()
        else:
            P.validate()

    def validator(self, instance, value):
        """validate the property class"""
        if not self._resolved:
            raise AttributeError(
                'Pointers are must be resolved with '
                "'Pointers.resolve()' before proceeding")
        if isinstance(self.ptype, (list, tuple)):
            for pt in self.ptype:
                if isinstance(value, pt):
                    return value
            if isinstance(value, dict):
                try:
                    return self.ptype[0](**value)
                except KeyError:
                    bad_key_str = ', '.join(value)
                    key_str = ', '.join(
                        [k for k in self.ptype[0]._exposed if k != 'meta'])
                    raise KeyError(
                        'Invalid input keywords [{}] for default pointer '
                        'type {}. The following are available: [{}]'.format(
                            bad_key_str, self.ptype[0].__name__, key_str))
            else:
                try:
                    return self.ptype[0](value)
                except TypeError:
                    ptype_str = ', '.join([p.__name__ for p in self.ptype])
                    raise TypeError(
                        'Invalid input type {}. You need to use one '
                        'of the following: [{}]'.format(
                            value.__class__.__name__, ptype_str))
        if not isinstance(value, self.ptype):
            if isinstance(value, dict):
                try:
                    # Setting a pointer from a dictionary,
                    # which are passed to %s as **kwargs.
                    return self.ptype(**value)
                except KeyError:
                    bad_key_str = ', '.join(value)
                    key_str = ', '.join(
                        [k for k in self.ptype._exposed if k != 'meta'])
                    raise KeyError(
                        'Invalid input keywords [{}] for pointer type {}. '
                        'The following are available: [{}]'.format(
                            bad_key_str, self.ptype.__name__, key_str))
            else:
                try:
                    return self.ptype(value)
                except TypeError:
                    raise TypeError(
                        'Invalid input type {}. You need to use {}'.format(
                            value.__class__.__name__, self.ptype.__name__))
        return value

    def get_extra_methods(self):
        """get methods from exposed properties"""
        if len(self.expose) > 0 and self.repeated:
            raise AttributeError(
                'Pointer cannot have repeated model with exposures.')
        scope = self

        def get_prop(prop_name):

            def fget(self):
                return getattr(getattr(self, scope.name), prop_name)

            def fset(self, val):
                return setattr(getattr(self, scope.name), prop_name, val)

            return property(fget=fget, fset=fset,
                            doc='Exposed property for {}'.format(prop_name))

        return {k: get_prop(k) for k in self.expose}

    def from_json(self, value):
        return json.loads(value)