"""Small display contract; business schemas and names remain in PocketBase."""
import re
from typing import Literal
from urllib.parse import quote, urlsplit, urlunsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from .errors import fail

KEY = re.compile(r'[a-zA-Z0-9_][a-zA-Z0-9_-]{0,63}')
FIELD = re.compile(r'[a-zA-Z_][a-zA-Z0-9_]{0,63}')


class Property(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    field: str
    label: str = Field(min_length=1, max_length=100)
    format: Literal['text', 'number', 'boolean', 'tags'] = 'text'


class Resource(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    field: str


class Display(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)
    title_field: str
    identifier_field: str
    properties: list[Property] = Field(default_factory=list, max_length=30)
    resources: dict[str, Resource] = Field(default_factory=dict, max_length=30)
    cover: str | None = None

    @model_validator(mode='after')
    def validate_fields(self):
        fields = [self.title_field, self.identifier_field]
        fields += [prop.field for prop in self.properties]
        fields += [resource.field for resource in self.resources.values()]
        if any(not FIELD.fullmatch(field) for field in fields):
            raise ValueError('Invalid field')
        if any(not KEY.fullmatch(slot) for slot in self.resources):
            raise ValueError('Invalid resource slot')
        if self.cover is not None and self.cover not in self.resources:
            raise ValueError('Unknown cover slot')
        # A resource path must never accidentally become a visible card property.
        visible = {self.title_field, self.identifier_field}
        visible.update(prop.field for prop in self.properties)
        if visible.intersection(r.field for r in self.resources.values()):
            raise ValueError('Resource fields cannot be displayed as text')
        return self


def configuration(record, request=None):
    try:
        return Display.model_validate(record['display'])
    except ValidationError as error:
        problems = ', '.join('.'.join(str(part) for part in item['loc']) + ': ' + item['msg']
                             for item in error.errors(include_input=False, include_context=False))
        fail(request, 503, 'display_invalid', '展示配置无效，请检查 display 的字段映射和资源槽位。',
             stage='display_config', reason=problems)
    except (KeyError, ValueError, TypeError):
        fail(request, 503, 'display_missing', '类型缺少有效的 display 展示配置。', stage='display_config')


def resource_url(gateway, path, request=None):
    """Only join a raw relative path to the administrator-configured gateway."""
    try:
        base = urlsplit(gateway)
        if (base.scheme not in ('http', 'https') or not base.hostname
                or base.username or base.password or base.query or base.fragment):
            raise ValueError()
        base.port  # Validate malformed ports before handing the URL to httpx.
        if (not isinstance(path, str) or not path or path.startswith('/')
                or any(char in path for char in '\\%?#')
                or any(ord(char) < 32 or ord(char) == 127 for char in path)
                or any(part in ('', '.', '..') for part in path.split('/'))):
            raise ValueError()
        url = urlunsplit((base.scheme, base.netloc,
                          base.path.rstrip('/') + '/' + quote(path, safe='/'), '', ''))
        httpx.URL(url)  # Reject malformed hosts before constructing an upstream request.
        return url
    except (ValueError, TypeError, AttributeError, httpx.InvalidURL):
        fail(request, 503, 'resource_config_invalid',
             '媒体网关或相对路径配置无效，请检查 media_gateway 和资源字段。', stage='resource_config')


def display_value(value, kind='text'):
    if kind == 'tags':
        return value if isinstance(value, list) and all(isinstance(v, str) for v in value) else None
    if kind == 'boolean':
        return value if isinstance(value, bool) else None
    if kind == 'number':
        return value if isinstance(value, (int, float)) and not isinstance(value, bool) else None
    return value if isinstance(value, (str, int, float, bool)) else None
