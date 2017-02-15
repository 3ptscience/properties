"""union.py: Union property"""
from __future__ import absolute_import
from __future__ import division
from __future__ import print_function
from __future__ import unicode_literals

from warnings import warn

from six import PY2

from ..base import HasProperties, Instance
from .. import basic
from .. import utils

if PY2:
    from types import ClassType                                                #pylint: disable=no-name-in-module
    CLASS_TYPES = (type, ClassType)
else:
    CLASS_TYPES = (type,)


class Union(basic.Property):
    """Union property of multiple property types

    Allowed keywords:

    * **props** - a list of the different valid property types. May also
      be HasProperties classes
    """

    class_info = 'a union of multiple property types'

    def __init__(self, doc, props, **kwargs):
        self.props = props
        super(Union, self).__init__(doc, **kwargs)
        self._unused_default_warning()

    @property
    def props(self):
        """List of valid property types or HasProperties classes"""
        return self._props

    @props.setter
    def props(self, value):
        if not isinstance(value, (tuple, list)):
            raise TypeError('props must be a list')
        new_props = tuple()
        for prop in value:
            if (isinstance(prop, CLASS_TYPES) and
                    issubclass(prop, HasProperties)):
                prop = Instance('', prop)
            if not isinstance(prop, basic.Property):
                raise TypeError('props must be Property instances or '
                                'HasProperties classes')
            new_props += (prop,)
        self._props = new_props

    @property
    def info(self):
        """Description of the property, supplemental to the basic doc"""
        return ' or '.join([p.info for p in self.props])

    @property
    def name(self):
        """The name of the property on a HasProperties class

        This is set in the metaclass. For Unions, props inherit the name.
        """
        return getattr(self, '_name', '')

    @name.setter
    def name(self, value):
        for prop in self.props:
            prop.name = value
        self._name = value

    @property
    def default(self):
        """Default value of the property"""
        prop_def = getattr(self, '_default', utils.undefined)
        for prop in self.props:
            if prop.default is utils.undefined:
                continue
            if prop_def is utils.undefined:
                prop_def = prop.default
                break
        return prop_def

    @default.setter
    def default(self, value):
        if value is utils.undefined:
            self._default = value
            return
        for prop in self.props:
            try:
                if callable(value):
                    prop.validate(None, value())
                else:
                    prop.validate(None, value)
                self._default = value
                return
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        raise TypeError('Invalid default for Union property')

    def _unused_default_warning(self):
        prop_def = getattr(self, '_default', utils.undefined)
        for prop in self.props:
            if prop.default is utils.undefined:
                continue
            if prop_def is utils.undefined:
                prop_def = prop.default
            elif prop_def != prop.default:
                warn('Union prop default ignored: {}'.format(prop.default),
                     RuntimeWarning)

    def validate(self, instance, value):
        """Check if value is a valid type of one of the Union props"""
        for prop in self.props:
            try:
                return prop.validate(instance, value)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        self.error(instance, value)

    def assert_valid(self, instance, value=None):
        """Check if the Union has a valid value"""
        valid = super(Union, self).assert_valid(instance, value)
        if not valid:
            return False
        for prop in self.props:
            try:
                return prop.assert_valid(instance, value)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        raise ValueError(
            'The "{name}" property of a {cls} instance has not been set '
            'correctly'.format(
                name=self.name,
                cls=instance.__class__.__name__
            )
        )

    def serialize(self, value, include_class=True, **kwargs):
        """Return a serialized value

        If no serializer is provided, it uses the serialize method of the
        prop corresponding to the value
        """
        if self.serializer is not None:
            return self.serializer(value, **kwargs)
        if value is None:
            return None
        for prop in self.props:
            try:
                prop.validate(None, value)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
            return prop.serialize(value, include_class, **kwargs)
        return self.to_json(value, **kwargs)

    def deserialize(self, value, trusted=False, **kwargs):
        """Return a deserialized value

        If no deserializer is provided, it uses the deserialize method of the
        prop corresponding to the value
        """
        if self.deserializer is not None:
            return self.deserializer(value, **kwargs)
        if value is None:
            return None
        for prop in self.props:
            try:
                return prop.deserialize(value, trusted, **kwargs)
            except (ValueError, KeyError, TypeError, AttributeError):
                continue
        return self.from_json(value, **kwargs)

    def equal(self, value_a, value_b):
        return any((prop.equal(value_a, value_b) for prop in self.props))

    @staticmethod
    def to_json(value, **kwargs):
        """Return value, serialized if value is a HasProperties instance"""
        if isinstance(value, HasProperties):
            return value.serialize(**kwargs)
        return value

    def sphinx_class(self):
        """Redefine sphinx class to provide doc links to types of props"""
        return ', '.join(p.sphinx_class() for p in self.props)
