OWNER = "Owner"
FACTORY_ADMIN = "Factory Admin"
SALESMAN = "Salesman"
PRODUCTION_SUPERVISOR = "Production Supervisor"
ACCOUNTANT_AUDITOR = "Accountant / Auditor"

ROLES = (
    OWNER,
    FACTORY_ADMIN,
    SALESMAN,
    PRODUCTION_SUPERVISOR,
    ACCOUNTANT_AUDITOR,
)

ROLE_ALIASES = {"Admin": FACTORY_ADMIN}


def canonical_role(role: str) -> str:
    return ROLE_ALIASES.get(role, role)
