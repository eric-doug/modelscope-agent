from typing import List, Optional

import json
import requests
from jsonschema import RefResolver
from pydantic import BaseModel, ValidationError
from requests.exceptions import RequestException, Timeout

from .tool import Tool

MAX_RETRY_TIMES = 3


class ParametersSchema(BaseModel):
    name: str
    description: str
    required: Optional[bool] = True


class ToolSchema(BaseModel):
    name: str
    description: str
    parameters: List[ParametersSchema]


class OpenAPISchemaTool(Tool):
    """
     openapi schema tool
    """
    name: str = 'api tool'
    description: str = 'This is a api tool that ...'
    parameters: list = []

    def __init__(self, cfg, name):
        self.name = name
        self.cfg = cfg.get(self.name, {})
        self.is_remote_tool = self.cfg.get('is_remote_tool', False)
        # remote call
        self.url = self.cfg.get('url', '')
        self.token = self.cfg.get('token', '')
        self.header = self.cfg.get('header', '')
        self.method = self.cfg.get('method', '')
        self.parameters = self.cfg.get('parameters', [])
        self.description = self.cfg.get('description',
                                        'This is a api tool that ...')
        self.responses_param = self.cfg.get('responses_param', [])
        try:
            all_para = {
                'name': self.name,
                'description': self.description,
                'parameters': self.parameters
            }
            self.tool_schema = ToolSchema(**all_para)
        except ValidationError:
            raise ValueError(f'Error when parsing parameters of {self.name}')
        self._str = self.tool_schema.model_dump_json()
        self._function = self.parse_pydantic_model_to_openai_function(all_para)

    def _remote_call(self, *args, **kwargs):
        if self.url == '':
            raise ValueError(
                f"Could not use remote call for {self.name} since this tool doesn't have a remote endpoint"
            )

        remote_parsed_input = json.dumps(
            self._remote_parse_input(*args, **kwargs))
        origin_result = None
        if self.method == 'POST':
            retry_times = MAX_RETRY_TIMES
            while retry_times:
                retry_times -= 1
                try:
                    response = requests.request(
                        'POST',
                        url=self.url,
                        headers=self.header,
                        data=remote_parsed_input)

                    if response.status_code != requests.codes.ok:
                        response.raise_for_status()
                    origin_result = json.loads(
                        response.content.decode('utf-8'))

                    final_result = self._parse_output(
                        origin_result, remote=True)
                    return final_result
                except Timeout:
                    continue
                except RequestException as e:
                    raise ValueError(
                        f'Remote call failed with error code: {e.response.status_code},\
                        error message: {e.response.content.decode("utf-8")}')

            raise ValueError(
                'Remote call max retry times exceeded! Please try to use local call.'
            )
        elif self.method == 'GET':
            retry_times = MAX_RETRY_TIMES
            while retry_times:
                retry_times -= 1
                try:
                    print('GET:', self.url)
                    response = requests.request(
                        'GET',
                        url=self.url,
                        headers=self.header,
                        params=remote_parsed_input)
                    if response.status_code != requests.codes.ok:
                        response.raise_for_status()

                    origin_result = json.loads(
                        response.content.decode('utf-8'))

                    final_result = self._parse_output(
                        origin_result, remote=True)
                    return final_result
                except Timeout:
                    continue
                except RequestException as e:
                    raise ValueError(
                        f'Remote call failed with error code: {e.response.status_code},\
                        error message: {e.response.content.decode("utf-8")}')

            raise ValueError(
                'Remote call max retry times exceeded! Please try to use local call.'
            )
        else:
            raise ValueError(
                'Remote call method is invalid!We have POST and GET method.')

    def _remote_parse_input(self, *args, **kwargs):
        model_name = kwargs.pop('model', '')
        if model_name == '':
            if self.parameters != []:
                model_name = self.parameters[0]['value'][0]
                kwargs['model'] = model_name
        else:
            kwargs['model'] = model_name
        restored_dict = {}
        for key, value in kwargs.items():
            if '.' in key:
                # Split keys by "." and create nested dictionary structures
                keys = key.split('.')
                temp_dict = restored_dict
                for k in keys[:-1]:
                    temp_dict = temp_dict.setdefault(k, {})
                temp_dict[keys[-1]] = value
            else:
                # f the key does not contain ".", directly store the key-value pair into restored_dict
                restored_dict[key] = value
            kwargs = restored_dict
        print('传给tool的参数：', kwargs)
        return kwargs


# openapi_schema_convert,register to tool_config.json
def extract_references(schema_content):
    references = []
    if isinstance(schema_content, dict):
        if '$ref' in schema_content:
            references.append(schema_content['$ref'])
        for key, value in schema_content.items():
            references.extend(extract_references(value))
    elif isinstance(schema_content, list):
        for item in schema_content:
            references.extend(extract_references(item))
    return references


def parse_nested_parameters(param_name, param_info, parameters_list, content):
    param_type = param_info['type']
    param_description = param_info.get('description',
                                       f'用户输入的{param_name}')  # 按需更改描述
    param_required = param_name in content['required']
    try:
        if param_type == 'object':
            properties = param_info.get('properties')
            if properties:
                # If the argument type is an object and has a non-empty "properties" field,
                # its internal properties are parsed recursively
                for inner_param_name, inner_param_info in properties.items():
                    param_type = inner_param_info['type']
                    param_description = inner_param_info.get(
                        'description', f'用户输入的{param_name}.{inner_param_name}')
                    param_required = param_name in content['required']
                    parameters_list.append({
                        'name':
                        f'{param_name}.{inner_param_name}',
                        'description':
                        param_description,
                        'required':
                        param_required,
                        'type':
                        param_type,
                        'value':
                        inner_param_info.get('enum', '')
                    })
        else:
            # Non-nested parameters are added directly to the parameter list
            parameters_list.append({
                'name': param_name,
                'description': param_description,
                'required': param_required,
                'type': param_type,
                'value': param_info.get('enum', '')
            })
    except Exception as e:
        raise ValueError(f'{e}:schema结构出错')


def parse_responses_parameters(param_name, param_info, parameters_list):
    param_type = param_info['type']
    param_description = param_info.get('description',
                                       f'调用api返回的{param_name}')  # 按需更改描述
    try:
        if param_type == 'object':
            properties = param_info.get('properties')
            if properties:
                # If the argument type is an object and has a non-empty "properties"
                # field, its internal properties are parsed recursively
                for inner_param_name, inner_param_info in properties.items():
                    param_type = inner_param_info['type']
                    param_description = inner_param_info.get(
                        'description',
                        f'调用api返回的{param_name}.{inner_param_name}')
                    parameters_list.append({
                        'name': f'{param_name}.{inner_param_name}',
                        'description': param_description,
                        'type': param_type,
                    })
        else:
            # Non-nested parameters are added directly to the parameter list
            parameters_list.append({
                'name': param_name,
                'description': param_description,
                'type': param_type,
            })
    except Exception as e:
        raise ValueError(f'{e}:schema结构出错')


def openapi_schema_convert(schema, YOUR_API_TOKEN=''):
    resolver = RefResolver.from_schema(schema)
    servers = schema.get('servers', [])
    if servers:
        servers_url = servers[0].get('url')
    else:
        print('No URL found in the schema.')
    # Extract endpoints
    endpoints = schema.get('paths', {})
    description = schema.get('info', {}).get('description',
                                             'This is a api tool that ...')
    config_data = {}
    # Iterate over each endpoint and its contents
    for endpoint_path, methods in endpoints.items():
        for method, details in methods.items():
            summary = details.get('summary', 'No summary').replace(' ', '_')
            name = details.get('operationId', 'No operationId')
            url = f'{servers_url}{endpoint_path}'
            security = details.get('security', [{}])
            # Security (Bearer Token)
            authorization = ''
            if security:
                for sec in security:
                    if 'BearerAuth' in sec:
                        authorization = f'Bearer {YOUR_API_TOKEN}'

            if method.upper() == 'POST':
                requestBody = details.get('requestBody', {})
                if requestBody:
                    for content_type, content_details in requestBody.get(
                            'content', {}).items():
                        schema_content = content_details.get('schema', {})
                        references = extract_references(schema_content)
                        for reference in references:
                            resolved_schema = resolver.resolve(reference)
                            content = resolved_schema[1]
                            parameters_list = []
                            for param_name, param_info in content[
                                    'properties'].items():
                                parse_nested_parameters(
                                    param_name, param_info, parameters_list,
                                    content)
                            X_DashScope_Async = requestBody.get(
                                'X-DashScope-Async', '')
                            if X_DashScope_Async == '':
                                config_entry = {
                                    'name': name,
                                    'description': description,
                                    'is_active': True,
                                    'is_remote_tool': True,
                                    'url': url,
                                    'method': method.upper(),
                                    'parameters': parameters_list,
                                    'header': {
                                        'Content-Type': content_type,
                                        'Authorization': authorization
                                    }
                                }
                            else:
                                config_entry = {
                                    'name': name,
                                    'description': description,
                                    'is_active': True,
                                    'is_remote_tool': True,
                                    'url': url,
                                    'method': method.upper(),
                                    'parameters': parameters_list,
                                    'header': {
                                        'Content-Type': content_type,
                                        'Authorization': authorization,
                                        'X-DashScope-Async': 'enable'
                                    }
                                }
                else:
                    config_entry = {
                        'name': name,
                        'description': description,
                        'is_active': True,
                        'is_remote_tool': True,
                        'url': url,
                        'method': method.upper(),
                        'parameters': [],
                        'header': {
                            'Content-Type': 'application/json',
                            'Authorization': authorization
                        }
                    }
            elif method.upper() == 'GET':
                parameters_list = []
                parameters_list = details.get('parameters', [])
                config_entry = {
                    'name': name,
                    'description': description,
                    'is_active': True,
                    'is_remote_tool': True,
                    'url': url,
                    'method': method.upper(),
                    'parameters': parameters_list,
                    'header': {
                        'Authorization': authorization
                    }
                }
            else:
                raise ('method is not POST or GET')

            config_data[summary] = config_entry
    return config_data
