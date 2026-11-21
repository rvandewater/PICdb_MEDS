"""PICdb codes that end in a unit, tested with suMEDS's shared `UnitComponentContract`.

The contract finds every code of the spec whose last component is a unit and evaluates it with
dftly, as MEDS-Extract does: the component is the unit stripped, `UNK` where a row records none
or a blank one, and the `unit` metadata stays the raw column. `expected_unit_events` pins the
events it finds, so a new code that ends in a unit is a conscious change here.
`require_unit_in_code` checks the other direction: every event whose `_metadata._self.unit` reads a
row column gives that unit in its code.
"""

from sumeds.testing.contracts import UnitComponentContract


class TestUnitComponents(UnitComponentContract):
    spec = "PICdb"
    expected_unit_events = (
        "V1.1.0/LABEVENTS/lab",
        "V1.1.0/CHARTEVENTS/chart",
        "V1.1.0/INPUTEVENTS/fluid_input",
        "V1.1.0/OUTPUTEVENTS/output",
        "V1.1.0/PRESCRIPTIONS/medication_start",
    )
    require_unit_in_code = True
