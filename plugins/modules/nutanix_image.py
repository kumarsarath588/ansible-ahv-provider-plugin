#!/usr/bin/python
# -*- coding: utf-8 -*-

# Copyright: (c) 2021, Balu George <balu.george@nutanix.com>
# GNU General Public License v3.0+ (see COPYING or https://www.gnu.org/licenses/gpl-3.0.txt)

from __future__ import (absolute_import, division, print_function)
__metaclass__ = type

DOCUMENTATION = r"""
---
module: nutanix_image

short_description: Images module which supports image crud operations

version_added: "0.0.1"

description: Create, update and delete Nutanix images

options:
    pc_hostname:
        description:
        - PC hostname or IP address
        type: str
        required: True
    pc_username:
        description:
        - PC username
        type: str
        required: True
    pc_password:
        description:
        - PC password
        required: True
        type: str
    pc_port:
        description:
        - PC port
        type: str
        default: 9440
    image_name:
        description:
        - Image name
        type: str
        required: True
    image_type:
        description:
        - Image type, ISO_IMAGE or DISK_IMAGE
        - Auto detetected based on image extension
        - Ignored if a value of vm_disk or vm_disk_uuid is specified
        type: str
    image_url:
        description:
        - Image url
        type: str
    vm_disk:
        description:
        - Name of VM Disk for image creation
        type: str
    vm_disk_uuid:
        description:
        - VM Disk UUID
        type: str
    image_uuid:
        description:
        - Image UUID
        - Specify image for update if there are multiple images with the same name
        type: str
    image_description:
        description:
        - Image description
        type: str
    image_checksum:
        description:
        - Checksum value and type of the image
        - Only applicable when image_url is specified
        type: dict
        suboptions:
            value:
                description:
                - Checksum value
                type: str
                required: True
            algorithm:
                description:
                - Checksum algorithm, SHA_1 or SHA_256
                type: str
                required: True
    clusters:
        description:
        - List of cluster names for image placement under these clusters
        - Image is placed directly on all clusters by default
        type: list
        elements: str
    data:
        description:
        - Filter payload
        - 'Valid attributes are:'
        - ' - C(length) (int): length'
        - ' - C(offset) (str): offset'
        type: dict
        default: {"offset": 0, "length": 500}
        suboptions:
            length:
                description:
                - Length
                type: int
            offset:
                description:
                - Offset
                type: int
    state:
        description:
        - Specify state of image
        - If C(state) is set to C(present) the image is created or updated
        - Image update operation only supports type and description fields
        - If C(state) is set to C(absent) and the image is present, all images with the specified name are removed
        type: str
        default: present
    validate_certs:
        description:
        - Set value to C(False) to skip validation for self signed certificates
        - This is not recommended for production setup
        type: bool
        default: True
author:
    - Balu George (@balugeorge)
"""

EXAMPLES = r"""
- name: Create/Update image
  nutanix.nutanix.nutanix_image:
    pc_hostname: "{{ pc_hostname }}"
    pc_username: "{{ pc_username }}"
    pc_password: "{{ pc_password }}"
    pc_port: 9440
    image_name: "{{ image_name }}"
    image_type: "{{ image_type }}"
    image_url: "{{ image_url }}"
    image_description: "{{ Image description }}"
    image_checksum:
        value: "{{ checksum_value }}"
        algorithm: "{{ checksum_algorithm }}"
    clusters:
    - "{{ cluster-1 }}"
    - "{{ cluster-2 }}"
    state: present
  delegate_to: localhost
  register: create_image
  async: 600
  poll: 0
- name: Wait for image creation
  async_status:
    jid: "{{ create_image.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 15
  delay: 10

- name: Delete image
  nutanix.nutanix.nutanix_image:
    pc_hostname: "{{ pc_hostname }}"
    pc_username: "{{ pc_username }}"
    pc_password: "{{ pc_password }}"
    pc_port: 9440
    image_name: "{{ image_name }}"
    state: absent
  delegate_to: localhost
  register: delete_image
  async: 600
  poll: 0
- name: Wait for image deletion
  async_status:
    jid: "{{ delete_image.ansible_job_id }}"
  register: job_result
  until: job_result.finished
  retries: 15
  delay: 10
"""

RETURN = r"""
## TO-DO
"""

import json
from os.path import splitext
from urllib.parse import urlparse
from ansible.module_utils.basic import AnsibleModule, env_fallback
from ansible_collections.nutanix.nutanix.plugins.module_utils.nutanix_api_client import (
    NutanixApiClient,
    create_image,
    update_image,
    list_entities,
    get_image,
    delete_image,
    task_poll)


CREATE_PAYLOAD = """{
  "spec": {
    "name": "IMAGE_NAME",
    "resources": {
      "image_type": "IMAGE_TYPE",
      "initial_placement_ref_list": [],
      "source_options": {
        "allow_insecure_connection": true
      }
    },
    "description": ""
  },
  "api_version": "3.1.0",
  "metadata": {
    "kind": "image",
    "name": "IMAGE_NAME"
  }
}"""


def set_list_payload(data):
    """
    Generate payload for pagination support
    * FIQL filters are not supported in images and clusters API
    * filter option is only meant for by vm list API(for getting VM UUID,
      used in image creation from VM Disk)
    """
    payload = {}

    if data:
        if "length" in data:
            payload["length"] = data["length"]
        if "offset" in data:
            payload["offset"] = data["offset"]
        if "filter" in data:
            payload["filter"] = data["filter"]

    return payload


def generate_argument_spec(result):
    """Generate a dict with all user arguments"""
    module_args = dict(
        pc_hostname=dict(type="str", required=True,
                         fallback=(env_fallback, ["PC_HOSTNAME"])),
        pc_username=dict(type="str", required=True,
                         fallback=(env_fallback, ["PC_USERNAME"])),
        pc_password=dict(type="str", required=True, no_log=True,
                         fallback=(env_fallback, ["PC_PASSWORD"])),
        pc_port=dict(type="str", default="9440"),
        image_name=dict(type="str", required=True),
        image_type=dict(type="str"),
        image_url=dict(type="str"),
        vm_disk=dict(type="str"),
        vm_disk_uuid=dict(type="str"),
        image_uuid=dict(type="str"),
        image_description=dict(type="str"),
        image_checksum=dict(
            type="dict",
            options=dict(
                value=dict(type="str", required=True),
                algorithm=dict(type="str", required=True)
            )
        ),
        clusters=dict(type="list", elements="str"),
        data=dict(
            type="dict",
            default={"offset": 0, "length": 500},
            options=dict(
                length=dict(type="int"),
                offset=dict(type="int")
            )
        ),
        state=dict(type="str", default="present"),
        validate_certs=dict(type="bool", default=True, fallback=(
            env_fallback, ["VALIDATE_CERTS"])),
    )

    module = AnsibleModule(
        argument_spec=module_args,
        mutually_exclusive=[("image_url", "vm_disk"),
                            ("vm_disk", "vm_disk_uuid"), ],
        required_one_of=[("image_url", "vm_disk", "vm_disk_uuid"), ],
        supports_check_mode=True
    )

    # Return initial result dict for dry run
    if module.check_mode:
        module.exit_json(**result)

    return module


def get_existing_image_state(module, client):
    """Check if an image is present in PC"""
    image_state = {"match_state": False, "match_name": False,
                   "match_type": False, "match_description": False}
    image_uuid = None
    image_name = module.params.get("image_name")
    image_type = module.params.get("image_type")
    image_description = module.params.get("image_description")
    image_url = module.params.get("image_url")
    payload = set_list_payload(module.params["data"])
    image_list_data = list_entities('images', payload, client)
    for entity in image_list_data["entities"]:
        if image_name == entity["status"]["name"]:
            existing_image_type = entity["status"]["resources"]["image_type"]
            existing_image_description = entity["status"].get("description")
            image_state["match_name"] = True
            image_uuid = entity["metadata"]["uuid"]
            if image_type == existing_image_type and image_description == existing_image_description:
                image_state["match_state"] = True
                break
            elif image_type == existing_image_type:
                image_state["match_type"] = True
                break
            elif image_description == existing_image_description:
                image_state["match_description"] = True
                break

    return image_state, image_uuid


def create_image_spec(module, client, result):
    """Generate spec for image creation"""
    cluster_validated = False
    cluster_name_and_uuid = {}
    image_name = module.params.get("image_name")
    image_url = module.params.get("image_url")
    vm_disk = module.params.get("vm_disk")
    vm_disk_uuid = module.params.get("vm_disk_uuid")
    image_type = module.params.get("image_type")
    image_description = module.params.get("image_description")
    image_checksum = module.params.get("image_checksum")
    clusters = module.params.get("clusters")
    create_payload = json.loads(CREATE_PAYLOAD)
    vm_list_payload = set_list_payload(module.params["data"])

    # Auto detect image_type based on url extension
    if not image_type:
        parsed_url = urlparse(image_url)
        path, extension = splitext(parsed_url.path)
        if extension == ".iso":
            image_type = "ISO_IMAGE"
        elif extension == ".qcow2":
            image_type = "DISK_IMAGE"
        else:
            module.fail_json(
                "Unable to identify image_type, specify the value manually")

    # Get VM UUID for image creation from VM Disk and update spec
    if vm_disk and not vm_disk_uuid:
        vm_list_payload["filter"] = "vm_name=={0}".format(vm_disk)
        vm_list_data = list_entities('vms', vm_list_payload, client)
        # vm_name is considered to be unique
        # To-do: check and validate vm_disk_uuid for VMs with multiple Disks
        vm_disk_uuid = vm_list_data["entities"][0]["status"]["resources"]["disk_list"][0]["uuid"]
    if vm_disk_uuid:
        create_payload["spec"]["resources"]["data_source_reference"] = {
            "kind": "vm_disk", "uuid": vm_disk_uuid}
        create_payload["spec"]["resources"]["image_type"] = "DISK_IMAGE"
    elif image_url:
        create_payload["spec"]["resources"]["image_type"] = image_type
        create_payload["spec"]["resources"]["source_uri"] = image_url

    # Add image checksum
    if image_url and image_checksum:
        create_payload["spec"]["resources"]["checksum"] = {
            "checksum_value": image_checksum["value"], "checksum_algorithm": image_checksum["algorithm"]}

    # Get cluster UUID
    if clusters:
        cluster_payload = set_list_payload(module.params.get("data"))
        cluster_data = list_entities('clusters', cluster_payload, client)
        for cluster_name in clusters:
            for entity in cluster_data["entities"]:
                if entity["status"]["name"] == cluster_name:
                    cluster_uuid = entity["metadata"]["uuid"]
                    cluster_name_and_uuid[cluster_name] = cluster_uuid
                    create_payload["spec"]["resources"]["initial_placement_ref_list"].append(
                        {'kind': 'cluster', 'uuid': cluster_uuid})
        if len(cluster_name_and_uuid) != len(clusters):
            for cluster_name in cluster_name_and_uuid:
                clusters.remove(cluster_name)
            module.fail_json(
                "Could not find cluster(s) with name {0}".format(str(clusters)))
    else:
        del create_payload["spec"]["resources"]["initial_placement_ref_list"]

    create_payload["metadata"]["name"] = image_name
    create_payload["spec"]["name"] = image_name
    if image_description:
        create_payload["spec"]["description"] = image_description

    return create_payload


def _create(module, client, result):
    """Create image"""
    image_count = 0
    image_uuid_list = []
    image_spec = create_image_spec(module, client, result)
    image_name = module.params.get("image_name")

    # Get existing image state
    image_state, image_uuid = get_existing_image_state(module, client)
    for state_name, state_value in image_state.items():
        if state_name == "match_state" and state_value:
            result["image_state"] = image_state
            module.exit_json(**result)
            return result
        elif state_name != "match_state" and state_value:
            return _update(module, client, result, image_uuid)

    # Create Image
    task_uuid, image_uuid = create_image(image_spec, client)

    task_status = task_poll(task_uuid, client)
    if task_status:
        result["failed"] = True
        result["msg"] = task_status
        return result

    result["image_uuid"] = image_uuid
    result["changed"] = True
    return result


def _update(module, client, result, image_uuid):
    """Update Image"""
    image_count = 0
    data = set_list_payload(module.params["data"])
    image_name = module.params.get("image_name")
    image_type = module.params.get("image_type")
    image_description = module.params.get("description")
    image_uuid_for_update = module.params.get("image_uuid")
    image_description = module.params.get("image_description")
    if image_uuid_for_update:
        image_uuid = image_uuid_for_update
    # Get image spec
    image_spec = get_image(image_uuid, client)

    # Update image spec
    del image_spec["status"]
    image_spec["spec"]["resources"]["image_type"] = image_type
    if image_description:
        image_spec["spec"]["description"] = image_description
    else:
        image_uuid = image_spec["metadata"]["uuid"]
        # Add empty description
        # This will clear existing description if playbook doesn't have image_description field
        image_spec["spec"]["description"] = ""

    # Update image
    task_uuid = update_image(image_uuid, image_spec, client)

    # Poll task status for image update
    task_status = task_poll(task_uuid, client)
    if task_status:
        result["failed"] = True
        result["msg"] = task_status
        return result

    result["changed"] = True
    return result


def _delete(module, client, result):
    """Delete image(s)"""
    image_count = 0
    task_uuid_list, image_list, image_uuid_list = [], [], []
    data = set_list_payload(module.params["data"])
    image_name = module.params.get("image_name")

    if image_name:
        image_list_data = list_entities('images', data, client)
        for entity in image_list_data["entities"]:
            if image_name == entity["status"]["name"]:
                image_uuid = entity["metadata"]["uuid"]
                image_uuid_list.append(image_uuid)
                image_update_spec = entity
                image_count += 1
            if image_count > 1:
                result["msg"] = "Found multiple images with name {0}".format(
                    image_name)
                result["failed"] = True
                return result
        if image_count == 0:
            return result
        if not image_uuid_list:
            return result
        elif image_count == 1:
            result["image_count"] = 1
            result["changed"] = True
            task_uuid = delete_image(image_uuid, client)
            # Check task status for removal of a single image
            if task_uuid:
                task_status = task_poll(task_uuid, client)
                if task_status:
                    result["failed"] = True
                    result["msg"] = task_status
                    return result
    else:
        result["failed"] = True
        return result

    # Check status of all deletion tasks for removal of multiple images with duplicate names
    if task_uuid_list:
        result["msg"] = []
        for tuuid in task_uuid_list:
            task_status = task_poll(tuuid, client)
            if task_status:
                result["failed"] = True
                result["msg"].append(task_status)
        return result

    return result


def main():
    """Main function"""
    # Seed result dict
    result_init = dict(
        changed=False,
        ansible_facts={},
    )

    # Generate arg spec and call function
    arg_spec = generate_argument_spec(result_init)

    # Create api client
    api_client = NutanixApiClient(arg_spec)
    if arg_spec.params.get("state") == "present":
        result = _create(arg_spec, api_client, result_init)
    elif arg_spec.params.get("state") == "absent":
        result = _delete(arg_spec, api_client, result_init)

    arg_spec.exit_json(**result)


if __name__ == "__main__":
    main()
