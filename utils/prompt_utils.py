from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence, TypeVar

import questionary
from prompt_toolkit.styles import Style


T = TypeVar("T")


QUESTIONARY_STYLE = Style.from_dict({
    "qmark": "fg:#000000",
    "question": "fg:#000000",
    "answer": "fg:#000000",
    "pointer": "fg:#000000",
    "highlighted": "fg:#000000 bg:#d9d9d9",
    "selected": "fg:#000000",
    "instruction": "fg:#444444",
    "text": "fg:#000000",
})


@dataclass(frozen=True)
class LabeledChoice:
    label: str
    value: str


def _ask_or_exit(result: T | None) -> T:
    if result is None:
        raise SystemExit("Cancelled.")
    return result


def select_choice(
    message: str,
    choices: Sequence[str],
    *,
    default: str | None = None,
    use_shortcuts: bool = True,
) -> str:
    result = questionary.select(
        message,
        choices=list(choices),
        default=default,
        use_shortcuts=use_shortcuts,
        style=QUESTIONARY_STYLE,
    ).ask()
    return _ask_or_exit(result)


def select_int_choice(
    message: str,
    choices: Sequence[int],
    *,
    default: int | None = None,
    use_shortcuts: bool = True,
) -> int:
    str_choices = [str(c) for c in choices]
    chosen = questionary.select(
        message,
        choices=str_choices,
        default=str(default) if default is not None else None,
        use_shortcuts=use_shortcuts,
        style=QUESTIONARY_STYLE,
    ).ask()
    return int(_ask_or_exit(chosen))


def autocomplete_label_value(
    message: str,
    items: Iterable[LabeledChoice],
    *,
    match_middle: bool = True,
    ignore_case: bool = True,
) -> str:
    item_list = list(items)
    label_to_value = {item.label: item.value for item in item_list}
    labels = [item.label for item in item_list]

    chosen_label = questionary.autocomplete(
        message,
        choices=labels,
        match_middle=match_middle,
        ignore_case=ignore_case,
        style=QUESTIONARY_STYLE,
    ).ask()

    chosen_label = _ask_or_exit(chosen_label)
    return label_to_value[chosen_label]


def autocomplete_object(
    message: str,
    objects: Sequence[T],
    *,
    label_getter,
    value_getter=None,
    match_middle: bool = True,
    ignore_case: bool = True,
) -> T:
    label_to_obj: dict[str, T] = {}

    for obj in objects:
        label = str(label_getter(obj)).strip()

        if label in label_to_obj and value_getter is not None:
            disambiguator = str(value_getter(obj)).strip()
            label = f"{label} ({disambiguator})"

        label_to_obj[label] = obj

    chosen_label = questionary.autocomplete(
        message,
        choices=list(label_to_obj.keys()),
        match_middle=match_middle,
        ignore_case=ignore_case,
        style=QUESTIONARY_STYLE,
    ).ask()

    chosen_label = _ask_or_exit(chosen_label)
    return label_to_obj[chosen_label]


def text_input(
    message: str,
    *,
    allow_blank: bool = True,
) -> str | None:
    value = input(f"{message}\n> ").strip()
    if not value and allow_blank:
        return None
    return value or None


def yes_no(
    message: str,
    *,
    default: bool = False,
) -> bool:
    result = questionary.confirm(
        message,
        default=default,
        style=QUESTIONARY_STYLE,
    ).ask()
    return bool(_ask_or_exit(result))


def prompt_scope_choice(
    message: str,
    *,
    default: str = "Player",
) -> str:
    return select_choice(
        message,
        ["Set", "Player"],
        default=default,
    )


def text_input_required(message: str) -> str:
    while True:
        value = text_input(message, allow_blank=False)
        value = (value or "").strip()
        if value:
            return value
        print("A value is required.")
