# -*- coding: utf-8 -*-
"""Compatibility migration suggestions for breaking changes.

For each breaking finding, generates a concrete suggestion on how to modify
the new spec to restore backward compatibility.
"""
from __future__ import annotations

from .models import DiffReport, Finding

_MIGRATION_ADVICE: dict[str, str] = {
    "endpoint_removed":
        "Restore the endpoint with a Sunset/deprecation header for one release cycle. "
        "Example: add 'x-deprecated: true' and return 410 Gone with a Location header.",
    "method_removed":
        "Restore the HTTP method and return 410 Gone with a Link header pointing to the replacement endpoint.",
    "parameter_removed":
        "Keep the parameter in the spec but mark it deprecated. Ignore it server-side instead of rejecting.",
    "parameter_required_raised":
        "Revert to optional. Enforce required at the business logic layer with a clear 400 error.",
    "required_parameter_added":
        "Make the parameter optional with a sensible default value. Enforce at the business logic layer.",
    "request_body_removed":
        "Keep accepting the request body but ignore its contents. Return 415 for truly unsupported media types.",
    "request_body_added_required":
        "Make the request body optional. Accept calls without it and use defaults.",
    "response_status_removed":
        "Restore the status code. Clients depend on it for error handling and control flow.",
    "schema_removed":
        "Keep the schema component in components/schemas and mark it deprecated in the description.",
    "schema_type_changed":
        "Add a new field with the new type and deprecate the old field. Remove after one release cycle.",
    "schema_type_removed":
        "Restore the type constraint or document the widened acceptance explicitly.",
    "field_removed":
        "Keep the field in responses (marked deprecated) for one cycle. Stop accepting it in requests.",
    "property_removed":
        "Keep the property in responses (marked deprecated) for one cycle. Stop accepting it in requests.",
    "required_field_added":
        "Make the field optional with a default value. Enforce required at the business logic layer.",
    "required_property_added":
        "Make the property optional with a default value. Enforce required at the business logic layer.",
    "enum_value_removed":
        "Keep the enum value in the schema. Reject it at the business logic layer with a clear error message.",
    "constraint_tightened":
        "Relax the constraint to the previous value. Enforce the tighter constraint at the business logic layer.",
    "content_type_removed":
        "Keep accepting the content type. Convert internally to the new format instead of rejecting.",
    "type_removed":
        "Restore the type and mark it @deprecated. Remove after one release cycle.",
    "type_kind_changed":
        "Create a new type with the new kind and deprecate the old one. Provide a adapter/resolver.",
    "field_type_changed":
        "Add a new field with the new type and deprecate the old field. Remove after one release cycle.",
    "field_type_became_non_null":
        "Keep the field nullable. Handle null cases in the new business logic instead of enforcing non-null.",
    "input_field_removed":
        "Keep the input field and ignore it server-side. Mark it @deprecated in the SDL.",
    "input_field_added_required":
        "Make the input field optional with a default value. Enforce required at the resolver layer.",
    "input_field_type_changed":
        "Add a new input field with the new type and deprecate the old one.",
    "argument_removed":
        "Keep the argument and ignore it in the resolver. Mark it @deprecated in the SDL.",
    "argument_added_required":
        "Make the argument optional with a default value. Enforce required at the resolver layer.",
    "argument_type_changed":
        "Add a new argument with the new type and deprecate the old one.",
    "union_member_removed":
        "Keep the union member type. Return it as null or a default in the resolver instead of removing.",
    "type_changed":
        "Add a new field/property with the new type and deprecate the old one.",
    "const_changed":
        "Accept both the old and new const values during a transition period. Use a oneOf schema.",
    "directive_removed":
        "Restore the directive definition. Ignore it in the runtime instead of removing it from the schema.",
    "prefix_items_removed":
        "Keep the prefix items. Changing tuple semantics breaks positional array access.",
    "prefix_item_type_changed":
        "Use a oneOf schema to accept both the old and new types during a transition period.",
    "contains_removed":
        "Restore the contains constraint or document the relaxed validation explicitly.",
    "dependent_required_added":
        "Remove the dependent requirement. Enforce it at the business logic layer instead.",
}


def suggest_migration(report: DiffReport) -> dict:
    """Generate migration suggestions for all breaking changes in the report."""
    breaking_findings = [f for f in report.findings if f.breaking and f.source == "confirmed"]

    suggestions = []
    for f in breaking_findings:
        advice = _MIGRATION_ADVICE.get(f.change_type, "Review the change and ensure backward compatibility.")
        suggestions.append({
            "change_type": f.change_type,
            "location": f.location,
            "severity": f.severity,
            "summary": f.summary,
            "migration": advice,
            "current_suggestion": f.suggestion,
        })

    return {
        "total_breaking": len(breaking_findings),
        "has_migration_path": len(suggestions) > 0,
        "suggestions": suggestions,
    }


def suggest_migration_for_finding(finding: Finding) -> str:
    """Get migration advice for a single finding."""
    if not finding.breaking:
        return "No migration needed — this is a non-breaking change."
    return _MIGRATION_ADVICE.get(
        finding.change_type,
        "Review the change and ensure backward compatibility."
    )
