"""Display-only adaptation; scientific identifiers and units stay in source records."""
import re

_PHYSICS = {
    'm_ll': r'$m_{\ell\ell}$', 'm_llj': r'$m_{\ell\ell j}$',
    'p_T': r'$p_{\mathrm{T}}$', 'pt': r'$p_{\mathrm{T}}$',
    'p_T_ll': r'$p_{\mathrm{T}}^{\ell\ell}$',
    'm_eff': r'$m_{\mathrm{eff}}$', 'm_jj': r'$m_{jj}$',
    'E_T_miss': r'$E_{\mathrm{T}}^{\mathrm{miss}}$',
    'MET': r'$E_{\mathrm{T}}^{\mathrm{miss}}$',
    'delta_phi': r'$\Delta\phi$', 'delta_eta': r'$\Delta\eta$',
    'mu_95': r'$\mu_{95}$', 'sigma': r'$\sigma$',
}
_ROOT = {'#tilde': r'\tilde', '#chi': r'\chi', '#pm': r'\pm',
         '#nu': r'\nu', '#ell': r'\ell', '#tau': r'\tau', '#mu': r'\mu',
         '#Delta': r'\Delta', '#rightarrow': r'\rightarrow',
         '#geq': r'\geq', '#leq': r'\leq', '#times': r'\times'}

_INTERNAL_REGION = re.compile(
    r'^(?:sr|cr|vr|region|cell|node|stage)[ _-]+\d+(?:[ _-]+(?:obs|bin|cell|node|stage|\d+))*$',
    re.IGNORECASE)
_OPAQUE_HASH = re.compile(r'^[a-fA-F0-9]{12,128}$')


def label_errors(value):
    """Allow scientific math, reject machine underscores outside math spans."""
    if not isinstance(value, str) or not value.strip():
        return ['nonempty display label required']
    if value.count('$') % 2:
        return ['unbalanced scientific math delimiter']
    plain = re.sub(r'\$[^$]*\$', '', value)
    errors = []
    if '_' in plain or '#' in plain:
        errors.append('machine identifier or ROOT markup outside scientific math')
    if _INTERNAL_REGION.fullmatch(plain.strip()) or _OPAQUE_HASH.fullmatch(plain.strip()):
        errors.append('unresolved internal identifier requires a supplied semantic display label')
    if any(ord(c) < 32 and c not in '\n\t' for c in value):
        errors.append('control character in display label')
    return errors


def display_label(identifier, explicit=None):
    """Known notation is rendered as math; unknown names retain every token."""
    value = explicit if explicit is not None else identifier
    if not isinstance(value, str) or not value.strip():
        raise ValueError('a nonempty identifier or explicit display label is required')
    value = value.strip()
    if explicit is not None:
        errors = label_errors(value)
        if errors:
            raise ValueError('; '.join(errors))
        return value
    if '$' in value:
        if value.count('$') % 2:
            raise ValueError('invalid supplied scientific math label')
        parts = re.split(r'(\$[^$]*\$)', value)
        value = ''.join(part if part.startswith('$') else part.replace('_', ' ') for part in parts)
        if label_errors(value):
            raise ValueError('invalid supplied scientific math label')
        return value
    if value in _PHYSICS:
        return _PHYSICS[value]
    if _INTERNAL_REGION.fullmatch(value) or _OPAQUE_HASH.fullmatch(value):
        raise ValueError('unresolved internal identifier requires a supplied semantic display label: ' + value)
    if any(token in value for token in _ROOT) or '\\' in value or re.search(r'[_^]\{', value):
        for token, replacement in _ROOT.items():
            value = value.replace(token, replacement)
        return '$' + value + '$'
    # This is a conservative spelling change, not a physics interpretation.
    # Paths, operators, digits and units remain visible; no token is discarded.
    return value.replace('_', ' ')


def unit_label(unit):
    if not isinstance(unit, str) or not unit.strip():
        raise ValueError('an explicit unit (including dimensionless) is required')
    if '$' in unit:
        return display_label(unit)
    if any(c in unit for c in ('^', '{', '}', '\\')):
        return '$' + unit + '$'
    if '_' in unit:
        raise ValueError('unit with subscripts requires an explicit scientific math label')
    return unit


def axis_label(axis):
    return display_label(axis['name'], axis.get('display_label')) + ' [' + unit_label(axis['unit']) + ']'


def figure_label_errors(fig):
    errors = []
    for i, ax in enumerate(fig.axes):
        labels = [ax.get_xlabel(), ax.get_ylabel(), ax.get_title()]
        labels += [t.get_text() for t in (*ax.get_xticklabels(), *ax.get_yticklabels())]
        legend = ax.get_legend()
        if legend is not None:
            labels += [t.get_text() for t in legend.get_texts()]
        for value in filter(None, labels):
            errors += [f'axes {i}: {error}: {value!r}' for error in label_errors(value)]
    for text in getattr(fig, 'texts', []):
        if text.get_text():
            errors += label_errors(text.get_text())
    for legend in getattr(fig, 'legends', []):
        for text in legend.get_texts():
            errors += label_errors(text.get_text())
    return errors
