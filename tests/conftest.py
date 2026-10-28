"""Test options. --neo4j-test-db names a separate Neo4j database for the live tests (loader revisions,
query fixtures); without it they are skipped. It must never be the server's home database."""

import pytest


def pytest_addoption(parser):
    parser.addoption("--neo4j-test-db", default=None,
                     help="a separate Neo4j database (name containing 'test') for the live tests")


@pytest.fixture(scope="session")
def neo4j_test_db(request):
    """(driver, database name), after checking the database is separate. Each live module empties and
    loads it itself."""
    name = request.config.getoption("--neo4j-test-db")
    if not name:
        pytest.skip("live test: pass --neo4j-test-db <database>")
    from kg.load.db import get_driver
    driver = get_driver()
    homes, _, _ = driver.execute_query("SHOW DATABASES YIELD name, home WHERE home RETURN name", database_="system")
    found, _, _ = driver.execute_query("SHOW DATABASES YIELD name WHERE name = $n RETURN name", n=name,
                                       database_="system")
    if "test" not in name or name in {r["name"] for r in homes} | {"neo4j", "system"}:
        driver.close()
        raise pytest.UsageError("refusing %r: the live tests need a separate database whose name contains 'test'" % name)
    if not found:
        driver.close()
        pytest.fail("database %r does not exist; create it first (CREATE DATABASE %s)" % (name, name))
    yield driver, name
    driver.close()


def reset_and_seed(driver, name):
    """Empty the test database (never the home one: neo4j_test_db checked it) and load concepts/."""
    from kg.load.facts import ensure_constraints
    from kg.load.seed import load as load_seed
    from kg.load.seed import read_seed
    driver.execute_query("MATCH (n) DETACH DELETE n", database_=name)
    seed = read_seed()
    ensure_constraints(driver, name)
    load_seed(driver, seed, name)
    return {n.id for n in seed.nodes}
