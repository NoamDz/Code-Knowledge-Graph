"""Handler that imports from sibling module via absolute import."""
import os
import json
import logging
from services.models import Task


def handle(name):
    task = Task(name)
    return task
