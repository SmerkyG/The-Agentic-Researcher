#!/bin/bash

register_sandbox_adapter podman 20

sandbox_podman_image_exists() {
    oci_image_exists podman
}

sandbox_podman_build_image() {
    oci_build_image podman
}

sandbox_podman_validate() {
    :
}

sandbox_podman_launch() {
    oci_launch podman "${1:-run}"
}
