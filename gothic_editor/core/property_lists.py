"""Schema-driven array rows; values remain Daedalus expressions."""
import re

from .properties_schema import property_key
from .scripts import mask_comments


def validate_expression(value):
    """Reject plain text and statement delimiters, leaving full parsing to the compiler."""
    code = mask_comments(value).strip()
    if not code:
        return not value.strip()
    tokens = re.findall(r'0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?|[A-Za-z_]\w*|[^\s]', code, re.ASCII)
    operand = re.compile(r'(?:0[xX][0-9a-fA-F]+|\d+(?:\.\d+)?|[A-Za-z_]\w*)\Z', re.ASCII)
    previous_operand = False
    for token in tokens:
        is_operand = operand.fullmatch(token) is not None
        if (not is_operand and token not in '()+-*/%<>=!&|^~.,') or (is_operand and previous_operand):
            return False
        previous_operand = is_operand
    return True


def display_value(value, kind):
    if kind == 'string' and re.fullmatch(r'"(?:\\.|[^"\\])*"', value):
        return re.sub(r'\\([\\"])', r'\1', value[1:-1])
    return value


def expression_value(value, kind):
    if kind == 'string' and value and not re.fullmatch(r'"(?:\\.|[^"\\])*"', value):
        return '"' + value.replace('\\', '\\\\').replace('"', '\\"') + '"'
    return value.strip() if kind != 'string' else value


class PropertyList:
    def __init__(self, field, fields):
        self.field = field
        self.fields = {property_key(key): value for key, value in fields.items()}
        self.reserved_indices = set()
        self.rows = []
        for index in range(field.start_index, field.start_index + field.max_rows):
            values = tuple(self.fields.get(self.key(column.key, index), '') for column in field.columns)
            if any(self.fields.get(self.key(key, index), '').casefold() == value.casefold()
                   for key, value in field.reserved):
                self.reserved_indices.add(index)
            elif any(values):
                self.rows.append((index, values))

    @staticmethod
    def key(variable, index):
        return property_key(f'{variable}[{index}]')

    def available_index(self, rows):
        occupied = self.reserved_indices | {index for index, _ in rows}
        return next((index for index in range(self.field.start_index,
                    self.field.start_index + self.field.max_rows) if index not in occupied), None)

    def updates(self, rows):
        indices = [index for index, _ in rows]
        allowed = set(range(self.field.start_index, self.field.start_index + self.field.max_rows))
        if (len(indices) != len(set(indices)) or not set(indices) <= allowed - self.reserved_indices
                or any(len(values) != len(self.field.columns) for _, values in rows)):
            raise ValueError('Invalid array rows')
        result = {}
        current = {index: values for index, values in rows}
        for index in allowed - self.reserved_indices:
            values = current.get(index, ('',) * len(self.field.columns))
            for column, value in zip(self.field.columns, values):
                key = self.key(column.key, index)
                if column.field_type == 'expression' and not validate_expression(value):
                    raise ValueError(f'{column.label} ({column.key}[{index}]): '
                                     'нужно число или выражение Daedalus, например 2 или BONUS + 2. '
                                     'Единицы измерения и другой текст укажите в текстовом поле строки.')
                if value != self.fields.get(key, ''):
                    result[key] = value
        return result
