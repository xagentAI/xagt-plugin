from __future__ import annotations

import re
from html.parser import HTMLParser

from services.account_service.console import (
    ACCOUNT_CONSOLE_CSS,
    ACCOUNT_CONSOLE_HTML,
    ACCOUNT_CONSOLE_JS,
)


class _Node:
    def __init__(
        self,
        tag: str,
        attributes: dict[str, str | None],
        parent: _Node | None,
    ) -> None:
        self.tag = tag
        self.attributes = attributes
        self.parent = parent


class _ConsoleHTMLParser(HTMLParser):
    _VOID_ELEMENTS = frozenset(
        {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }
    )

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.nodes: list[_Node] = []
        self._root = _Node("#document", {}, None)
        self._stack = [self._root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(
            tag,
            dict(attrs),
            self._stack[-1],
        )
        self.nodes.append(node)
        if tag.lower() not in self._VOID_ELEMENTS:
            self._stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = _Node(
            tag,
            dict(attrs),
            self._stack[-1],
        )
        self.nodes.append(node)

    def handle_endtag(self, tag: str) -> None:
        for index in range(len(self._stack) - 1, 0, -1):
            if self._stack[index].tag == tag:
                del self._stack[index:]
                return


_EMBEDDED_SELECTOR = re.compile(r'''\$\(\s*(["'])(#embedded-[^"']+)\1\s*\)''')
_HIDDEN_AUTHORIZATION_SECTION = re.compile(
    r'''body\[data-account-view="authorization"\]\s+main\s*>\s*'''
    r'''section\[aria-labelledby="([^"]+)"\]'''
)
_CSS_RULE = re.compile(r"(?P<selectors>[^{}]+)\{(?P<declarations>[^{}]+)\}")
_UPDATE_RECOVERY_FUNCTION = re.compile(
    r"const\s+updatePendingAllowanceRecovery\s*=\s*\(\)\s*=>\s*\{"
    r"(?P<body>.*?)\n\s*\};",
    re.DOTALL,
)


def _parse_console_html() -> _ConsoleHTMLParser:
    parser = _ConsoleHTMLParser()
    parser.feed(ACCOUNT_CONSOLE_HTML)
    parser.close()
    return parser


def _hidden_authorization_section_labels() -> set[str]:
    labels: set[str] = set()
    for rule in _CSS_RULE.finditer(ACCOUNT_CONSOLE_CSS):
        if not re.search(r"display\s*:\s*none", rule.group("declarations")):
            continue
        labels.update(_HIDDEN_AUTHORIZATION_SECTION.findall(rule.group("selectors")))
    return labels


def _is_descendant(node: _Node, ancestor: _Node) -> bool:
    current = node.parent
    while current is not None:
        if current is ancestor:
            return True
        current = current.parent
    return False


def _has_recovery_binding(selector: str) -> bool:
    escaped_selector = re.escape(selector)
    binding = re.compile(
        rf'''\$\(\s*["']{escaped_selector}["']\s*\)\??\.\s*'''
        r'''addEventListener\(\s*["']click["']\s*,'''
    )
    direct_handler = re.compile(r"^\s*recoverPendingAllowance\s*\)")
    for match in binding.finditer(ACCOUNT_CONSOLE_JS):
        handler = ACCOUNT_CONSOLE_JS[match.end() : match.end() + 1200]
        if direct_handler.search(handler):
            return True
        callback_end = re.search(r"\n\s*\}\);", handler)
        if callback_end and "recoverPendingAllowance" in handler[: callback_end.start()]:
            return True
    return False


def _has_dynamic_embedded_recovery_container() -> bool:
    function = _UPDATE_RECOVERY_FUNCTION.search(ACCOUNT_CONSOLE_JS)
    if function is None:
        return False
    body = function.group("body")
    return (
        re.search(
            r'''const\s+embeddedContainer\s*=\s*\$\(\s*["']#embedded-pending-recovery["']\s*\);''',
            body,
        )
        is not None
        and re.search(
            r"embeddedContainer\.hidden\s*=\s*!\(\s*hasPending\b",
            body,
        )
        is not None
    )


def _hidden_parent_section_or_plan(node: _Node) -> _Node | None:
    current = node.parent
    while current is not None:
        classes = set((current.attributes.get("class") or "").split())
        if (
            "hidden" in current.attributes
            and (current.tag == "section" or "embedded-plan" in classes)
        ):
            if (
                current.attributes.get("id") == "embedded-pending-recovery"
                and _has_dynamic_embedded_recovery_container()
            ):
                current = current.parent
                continue
            return current
        current = current.parent
    return None


def test_literal_embedded_query_selectors_have_real_html_targets() -> None:
    parser = _parse_console_html()
    html_ids = {
        f"#{node.attributes['id']}"
        for node in parser.nodes
        if "id" in node.attributes
    }
    javascript_selectors = {
        match.group(2) for match in _EMBEDDED_SELECTOR.finditer(ACCOUNT_CONSOLE_JS)
    }

    assert not (javascript_selectors - html_ids), (
        "ACCOUNT_CONSOLE_JS queries embedded elements missing from ACCOUNT_CONSOLE_HTML: "
        + ", ".join(sorted(javascript_selectors - html_ids))
    )


def test_allowance_recovery_button_is_not_inside_hidden_legacy_section() -> None:
    parser = _parse_console_html()
    buttons_by_id = {
        node.attributes["id"]: node
        for node in parser.nodes
        if node.tag == "button" and "id" in node.attributes
    }
    embedded_proxy = buttons_by_id.get("embedded-verify-pending-allowance")
    if embedded_proxy is not None:
        recovery_buttons = [embedded_proxy]
        embedded_region = next(
            (
                node
                for node in parser.nodes
                if node.attributes.get("id") == "embedded-authorization"
            ),
            None,
        )
        assert embedded_region is not None and _is_descendant(embedded_proxy, embedded_region), (
            "The embedded allowance recovery proxy must live in the embedded authorization region"
        )
        assert _has_recovery_binding("#embedded-verify-pending-allowance"), (
            "The embedded allowance recovery proxy must invoke recoverPendingAllowance"
        )
    else:
        shared_button = buttons_by_id.get("verify-pending-allowance")
        assert shared_button is not None, (
            "The embedded console must expose an allowance recovery button"
        )
        recovery_buttons = [shared_button]
        assert _has_recovery_binding("#verify-pending-allowance"), (
            "The shared allowance recovery button must invoke recoverPendingAllowance"
        )

    hidden_labels = _hidden_authorization_section_labels()
    hidden_sections = [
        node
        for node in parser.nodes
        if (
            node.tag == "section"
            and node.parent is not None
            and node.parent.tag == "main"
            and node.attributes.get("aria-labelledby") in hidden_labels
        )
    ]
    misplaced = []
    for button in recovery_buttons:
        if any(_is_descendant(button, section) for section in hidden_sections):
            misplaced.append(f"#{button.attributes['id']} (CSS-hidden legacy section)")
        hidden_parent = _hidden_parent_section_or_plan(button)
        if hidden_parent is not None:
            misplaced.append(
                f"#{button.attributes['id']} (hidden parent {hidden_parent.attributes.get('id', hidden_parent.tag)})"
            )

    assert not misplaced, (
        "Allowance recovery buttons must remain available in the embedded view; "
        "these have a hidden legacy section/plan ancestor: "
        + ", ".join(sorted(misplaced))
    )
