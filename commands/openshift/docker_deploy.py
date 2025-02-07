#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""ocp-deployer.py: Deployment script for OpenShift Container Platform"""
import os
import pathlib

import click
import docker
import urllib3
from docker.errors import APIError
from ocpconfig import environments, environment_name, dry_run
from ruamel.yaml import YAML
from slackconfig import channel_deployment, username_deployment

from commands import gyrobot, chat

urllib3.disable_warnings()

usernames = dict()
yaml = YAML()


def _deploy_config():
    if os.environ['DOCKER_DEPLOY_CONFIGURATION'].startswith('/'):
        config_file = pathlib.Path(os.environ['DOCKER_DEPLOY_CONFIGURATION'])
    else:
        config_file = pathlib.Path('config') / os.environ['DOCKER_DEPLOY_CONFIGURATION']

    with config_file.open() as f:
        docker_deploy_config = yaml.load(f)
    with config_file.with_suffix('.credentials.yaml').open() as f:
        docker_deploy_credentials = yaml.load(f)

    for env in docker_deploy_config['environments']:
        if env in docker_deploy_credentials:
            docker_deploy_config['environments'][env]['secret'] = docker_deploy_credentials[env]
    return docker_deploy_config


@gyrobot.command('deploy')
@click.argument('microservice')
@click.argument('version')
@click.argument('source_env')
@click.argument('target_env')
@click.argument('dry_run')
@click.pass_context
def deploy(ctx, microservice, version, source_env, target_env, dry_run=False):
    """Pull microservice image from source env and push to target env"""
    chat(ctx).send_text("Not implemented yet!", is_error=True)
    return


    source_registry_prefix_template = environments[source_env]['registry']
    target_registry_prefix_template = environments[target_env]['registry']

    source_image = source_registry_prefix_template.substitute(
        env=environment_name.get(source_env, source_env)) + microservice
    target_image = target_registry_prefix_template.substitute(
        env=environment_name.get(target_env, target_env)) + microservice

    client = docker.from_env()
    source_auth_config = {"username": environments[source_env]['user'], "password": environments[source_env]['secret']}
    target_auth_config = {"username": environments[target_env]['user'], "password": environments[target_env]['secret']}
    tag_with_env_name = environments[target_env]['tagWithEnv'].lower() == 'true'

    chat(ctx).send_text(f"Pulling {source_image}:{version} from {source_env}")

    image = None
    try:
        if not dry_run:
            image = client.images.pull(source_image, version, auth_config=source_auth_config)
            image.tag(target_image, version)

        msg = f"Tagged, pushing {target_image}:{version} to {target_env} ... "
        if not dry_run:
            msg += "Success" if client.images.push(target_image, version, auth_config=target_auth_config) else "Failed"
            client.images.remove(target_image + ":" + version)
        else:
            msg += "(dry run)"
        chat(ctx).send_text(msg)

        if tag_with_env_name:
            target_env = environment_name[target_env] if target_env in environment_name else target_env
            msg = f"Tagged, pushing {target_image}:{target_env} to {target_env} ... "
            if not dry_run:
                image.tag(target_image, target_env)
                msg += "Success" if client.images.push(target_image, target_env,
                                                       auth_config=target_auth_config) else "Failed"
                client.images.remove(target_image + ":" + target_env)
            else:
                msg += "(dry run)"
            chat(ctx).send_text(msg)

        if not dry_run:
            client.images.remove(source_image + ":" + version)
    except APIError as e:
        chat(ctx).send_text(f"*Failed with error {e}*")


def _handle_message(m: dict):
    """Handle message"""
    channel = m['channel']
    if channel != channel_deployment:
        return

    if 'message' in m:
        m = m['message']

    if 'username' in m and m['username'] == username_deployment:
        return

    if 'subtype' in m and m['subtype'] == 'message_deleted':
        return

    text = m['text']
    parts = text.split('/')

    if len(parts) != 4:
        chat(ctx).send_text("*Usage: <microservice>/<version>/<source_env>/<target_env>*")
        chat(ctx).send_text(f"*Environments supported: {list(environments.keys())}*")
        return
    if not parts[2] in environments.keys():
        chat(ctx).send_text(f"*{parts[2]}* environment not recognized")
        return
    if not parts[3] in environments.keys():
        chat(ctx).send_text(f"*{parts[3]}* environment not recognized")
        return

    deploy(parts[0], parts[1], parts[2], parts[3], dry_run=dry_run)
