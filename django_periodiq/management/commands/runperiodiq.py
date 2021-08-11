import os
import importlib
import pkgutil
import sys

from django.apps import apps
from django.conf import settings
from django.core.management.base import BaseCommand
from django.utils.module_loading import module_has_submodule
from periodiq import entrypoint


class Command(BaseCommand):
    help = "Runs Periodiq process."

    def add_arguments(self, parser):
        parser.add_argument(
            "--path", "-P",
            default=".",
            nargs="*",
            type=str,
            help="The import path (default: .).",
        )
        parser.add_argument(
            "--pid-file",
            type=str,
            help="write the PID of the master process to a file (default: no pid file)",
        )
        parser.add_argument(
            "--log-file",
            type=str,
            help="write all logs to a file (default: sys.stderr)",
        )

    def handle(self, path, verbosity, pid_file, log_file, **options):
        executable_name = "periodiq"
        executable_path = self._resolve_executable(executable_name)
        verbosity_args = ["-v"] * (verbosity - 1)

        tasks_modules = self.discover_tasks_modules()
        process_args = [
            executable_name,
            # -v -v ...
            *verbosity_args,
            # django_dramatiq.tasks app1.tasks app2.tasks ...
            *tasks_modules,
            "--path", *path,
        ]

        if pid_file:
            process_args.extend(["--pid-file", pid_file])

        if log_file:
            process_args.extend(["--log-file", log_file])

        self.stdout.write(' * Running periodiq: "%s"\n\n' % " ".join(process_args))
        if os.name == 'nt':
            sys.argv = process_args
            entrypoint()
        else:
            os.execvp(executable_path, process_args)

    def discover_tasks_modules(self):
        task_module_names = getattr(settings, "DRAMATIQ_AUTODISCOVER_MODULES", ("tasks",))
        ignored_modules = set(getattr(settings, "DRAMATIQ_IGNORED_MODULES", []))
        app_configs = []
        for conf in apps.get_app_configs():
            # Always find our own tasks, regardless of the configured module names.
            if conf.name == "django_dramatiq":
                app_configs.append((conf, "tasks"))
            else:
                for task_module in task_module_names:
                    if module_has_submodule(conf.module, task_module):
                        app_configs.append((conf, task_module))
        tasks_modules = ["django_dramatiq.setup"]

        def is_ignored_module(module_name):
            if not ignored_modules:
                return False

            if module_name in ignored_modules:
                return True

            name_parts = module_name.split(".")

            for c in range(1, len(name_parts)):
                part_name = ".".join(name_parts[:c]) + ".*"
                if part_name in ignored_modules:
                    return True

            return False

        for conf, task_module in app_configs:
            module = conf.name + "." + task_module
            if is_ignored_module(module):
                self.stdout.write(" * Ignored tasks module: %r" % module)
                continue

            imported_module = importlib.import_module(module)
            if not self._is_package(imported_module):
                self.stdout.write(" * Discovered tasks module: %r" % module)
                tasks_modules.append(module)
            else:
                submodules = self._get_submodules(imported_module)

                for submodule in submodules:
                    if is_ignored_module(submodule):
                        self.stdout.write(" * Ignored tasks module: %r" % submodule)
                    else:
                        self.stdout.write(" * Discovered tasks module: %r" % submodule)
                        tasks_modules.append(submodule)

        return tasks_modules

    def _is_package(self, module):
        return hasattr(module, "__path__")

    def _get_submodules(self, package):
        submodules = []

        package_path = package.__path__
        prefix = package.__name__ + "."

        for _, module_name, _ in pkgutil.walk_packages(package_path, prefix):
            submodules.append(module_name)

        return submodules

    def _resolve_executable(self, exec_name):
        bin_dir = os.path.dirname(sys.executable)
        if bin_dir:
            return os.path.join(bin_dir, exec_name)
        return exec_name
