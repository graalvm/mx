from .. import mx


def iter_projects(suite, fn):
    processed_suites = {suite.name}

    def _mx_projects_suite(_, suite_import):
        if suite_import.name in processed_suites:
            return
        processed_suites.add(suite_import.name)
        dep_suite = mx.suite(suite_import.name)
        fn(dep_suite, suite_import.name)
        dep_suite.visit_imports(_mx_projects_suite)

    suite.visit_imports(_mx_projects_suite)
