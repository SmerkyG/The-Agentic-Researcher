#!/bin/bash

register_sandbox_adapter docker 10

sandbox_docker_image_exists() {
    oci_image_exists docker
}

sandbox_docker_build_image() {
    oci_build_image docker
}

sandbox_docker_validate() {
    :
}

sandbox_docker_launch() {
    oci_launch docker "${1:-run}"
}
