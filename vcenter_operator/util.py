import re


def parse_buildingblock(bb, leading_zero=True):
    if bb is None:
        return

    if not isinstance(bb, int):
        m = re.match(r'^b?b?(?P<num>\d+)$', bb.lower())
        if not m:
            raise ValueError(f'"{bb}" is not a valid building block')

        bb = int(m.group('num'))

    if leading_zero:
        return f'bb{bb:03}'
    else:
        return f'bb{bb}'
