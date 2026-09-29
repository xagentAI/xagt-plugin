# -*- coding: utf-8 -*-
"""Built-in regression corpus for the deterministic diff engines.

Each sample pairs an old/new contract with the ground-truth answer
(``expected_breaking``). ``run_benchmark`` in :mod:`app.benchmark` replays
every sample through the engines and reports precision / recall / F1, which
makes the "deterministic and reproducible" claim measurable by judges.
"""

_PETS_API_V1 = """openapi: 3.0.3
info: {title: Pets, version: 1.0.0}
paths:
  /pets:
    get:
      operationId: listPets
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Pet'
    post:
      operationId: createPet
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/NewPet'
      responses:
        '201':
          description: created
  /pets/{id}:
    get:
      operationId: getPet
      responses:
        '200':
          description: ok
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/Pet'
components:
  schemas:
    Pet:
      type: object
      required: [id, name]
      properties:
        id: {type: integer}
        name: {type: string, maxLength: 50}
        status: {type: string, enum: [available, pending, sold]}
    NewPet:
      type: object
      required: [name]
      properties:
        name: {type: string, maxLength: 50}
"""


def _with_endpoint_removed() -> tuple[str, str]:
    old = _PETS_API_V1
    new = _PETS_API_V1.replace("  /pets/{id}:\n    get:\n      operationId: getPet\n", "")
    return old, new


def _with_pets_get_removed() -> tuple[str, str]:
    old = _PETS_API_V1
    new = _PETS_API_V1.replace(
        "    get:\n      operationId: listPets\n"
        "      responses:\n"
        "        '200':\n"
        "          description: ok\n"
        "          content:\n"
        "            application/json:\n"
        "              schema:\n"
        "                $ref: '#/components/schemas/Pet'\n",
        "",
    )
    return old, new


def _with_field_added() -> tuple[str, str]:
    old = _PETS_API_V1
    new = _PETS_API_V1.replace(
        "        status: {type: string, enum: [available, pending, sold]}",
        "        status: {type: string, enum: [available, pending, sold]}\n"
        "        tag: {type: string}",
    )
    return old, new


def _with_enum_value_removed() -> tuple[str, str]:
    old = _PETS_API_V1
    new = _PETS_API_V1.replace(
        "enum: [available, pending, sold]", "enum: [available, sold]"
    )
    return old, new


def _with_required_added() -> tuple[str, str]:
    old = _PETS_API_V1
    new = old.replace(
        "required: [id, name]",
        "required: [id, name, status]",
    )
    return old, new


def _with_type_changed() -> tuple[str, str]:
    old = _PETS_API_V1
    new = old.replace("id: {type: integer}", "id: {type: string}")
    return old, new


def _with_maxlength_reduced() -> tuple[str, str]:
    old = _PETS_API_V1
    new = old.replace("name: {type: string, maxLength: 50}", "name: {type: string, maxLength: 10}")
    return old, new


def _with_deprecated() -> tuple[str, str]:
    old = _PETS_API_V1
    new = old.replace(
        "    get:\n      operationId: listPets",
        "    get:\n      operationId: listPets\n      deprecated: true",
    )
    return old, new


_GRAPHQL_V1 = """type Query {
  pet(id: ID!): Pet
  pets: [Pet!]!
}

type Pet {
  id: ID!
  name: String!
  age: Int
  status: Status!
}

enum Status {
  AVAILABLE
  PENDING
  SOLD
}
"""


def _gql_type_removed() -> tuple[str, str]:
    return _GRAPHQL_V1, _GRAPHQL_V1.replace("  status: Status!\n", "").replace(
        "enum Status {\n  AVAILABLE\n  PENDING\n  SOLD\n}\n", ""
    )


def _gql_field_added() -> tuple[str, str]:
    return _GRAPHQL_V1, _GRAPHQL_V1.replace("  status: Status!\n", "  status: Status!\n  tag: String\n")


def _gql_non_null_added() -> tuple[str, str]:
    return _GRAPHQL_V1, _GRAPHQL_V1.replace("  age: Int\n", "  age: Int!\n")


def _gql_field_deprecated() -> tuple[str, str]:
    return _GRAPHQL_V1, _GRAPHQL_V1.replace(
        "  age: Int\n", '  age: Int @deprecated(reason: "use pets")\n'
    )


_JSON_V1 = """{
  "$schema": "https://json-schema.org/draft/2020-12/schema",
  "type": "object",
  "required": ["id", "name"],
  "properties": {
    "id": {"type": "integer"},
    "name": {"type": "string", "maxLength": 50},
    "status": {"type": "string", "enum": ["available", "pending", "sold"]}
  }
}
"""


def _json_property_removed() -> tuple[str, str]:
    return _JSON_V1, _JSON_V1.replace(
        '    "name": {"type": "string", "maxLength": 50},\n    "status": {"type": "string", "enum": ["available", "pending", "sold"]}\n',
        '    "name": {"type": "string", "maxLength": 50}\n',
    )


def _json_property_added() -> tuple[str, str]:
    return _JSON_V1, _JSON_V1.replace(
        '    "status": {"type": "string", "enum": ["available", "pending", "sold"]},\n',
        '    "status": {"type": "string", "enum": ["available", "pending", "sold"]},\n    "tag": {"type": "string"},\n',
    )


def _json_type_changed() -> tuple[str, str]:
    return _JSON_V1, _JSON_V1.replace('"id": {"type": "integer"}', '"id": {"type": "string"}')


def _json_maxlength_reduced() -> tuple[str, str]:
    return _JSON_V1, _JSON_V1.replace('"name": {"type": "string", "maxLength": 50}', '"name": {"type": "string", "maxLength": 10}')


# Name -> (format, old, new, expected_breaking)
CORPUS = [
    # --- OpenAPI ---
    ("openapi.endpoint_removed", "openapi", *_with_endpoint_removed(), True),
    ("openapi.operation_removed", "openapi", *_with_pets_get_removed(), True),
    ("openapi.field_added", "openapi", *_with_field_added(), False),
    ("openapi.enum_value_removed", "openapi", *_with_enum_value_removed(), True),
    ("openapi.required_field_added", "openapi", *_with_required_added(), True),
    ("openapi.type_changed", "openapi", *_with_type_changed(), True),
    ("openapi.maxLength_reduced", "openapi", *_with_maxlength_reduced(), True),
    ("openapi.operation_deprecated", "openapi", *_with_deprecated(), False),
    # --- GraphQL ---
    ("graphql.type_removed", "graphql", *_gql_type_removed(), True),
    ("graphql.field_added", "graphql", *_gql_field_added(), False),
    ("graphql.field_became_non_null", "graphql", *_gql_non_null_added(), True),
    ("graphql.field_deprecated", "graphql", *_gql_field_deprecated(), False),
    # --- JSON Schema ---
    ("json.property_removed", "json-schema", *_json_property_removed(), True),
    ("json.property_added", "json-schema", *_json_property_added(), False),
    ("json.type_changed", "json-schema", *_json_type_changed(), True),
    ("json.maxLength_reduced", "json-schema", *_json_maxlength_reduced(), True),
]