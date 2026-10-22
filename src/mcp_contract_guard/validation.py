"""Validator customization for predictable decimal multipleOf evaluation."""

from fractions import Fraction

from jsonschema import Draft202012Validator, validators
from jsonschema.exceptions import ValidationError


def _multiple_of(validator, divisor, instance, schema):
    if not validator.is_type(instance, "number"):
        return
    # jsonschema's default binary-float division rejects ordinary decimal pairs
    # such as 0.3 / 0.1 and can overflow for a large integer divided by a float.
    # JSON numbers have already been parsed. Interpret their decimal spelling
    # exactly here, without float division or a tolerance that accepts bad data.
    ratio = Fraction(str(instance)) / Fraction(str(divisor))
    if ratio.denominator != 1:
        yield ValidationError("Number is not an exact decimal multiple of the declared divisor.")


GuardValidator = validators.extend(Draft202012Validator, {"multipleOf": _multiple_of})
