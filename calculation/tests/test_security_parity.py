"""
Security parity of calculationParams: the instance named by (instanceClassName, instanceId)
was loaded from any model by ContentType and client id, unscoped. Only a class the rules
link to `className` is loaded now, and only a row the user may read (the model's row
security, core target_queryset).

Fixture: core.test_helpers.create_security_tree -> R1>D1>W1>V1 / R2>D2>W2>V2, an insuree in
each village; the user holds the calculation right and is assigned district D1 only.
"""
import json

from django.core.cache import cache
from django.dispatch import Signal
from django.test import override_settings

from calculation.apps import CALCULATION_RULES, CalculationConfig
from core import datetime
from core.abs_calculation_rule import AbsStrategy
from core.models.openimis_graphql_test_case import openIMISGraphQLTestCase
from core.test_helpers import create_security_tree, create_right_only_user, get_test_token, perm_ids
from insuree.test_helpers import create_test_insuree

PARAM = {"type": "number", "name": "sp_rate", "label": {"en": "Rate", "fr": "Taux"},
         "rights": {"read": "153001"}, "relevance": "True", "condition": "INPUT>0", "default": "1"}


class SecurityParityRule(AbsStrategy):
    """Links `SPHolder` to Insuree, and gives a parameter for any instance it is handed.
    On this release the calculation services reach the rules through their signals."""
    signal_get_rule_name = Signal([])
    signal_get_rule_details = Signal([])
    signal_get_param = Signal([])
    signal_get_linked_class = Signal([])
    signal_calculate_event = Signal([])
    signal_convert_from_to = Signal([])
    version = 1
    uuid = "5e5e5e5e-0000-4000-8000-000000000001"
    calculation_rule_name = "Security parity rule"
    description = "test rule"
    impacted_class_parameter = [{"class": "SPHolder", "parameters": [PARAM]}]
    date_valid_from = datetime.datetime(2000, 1, 1)
    date_valid_to = None
    status = "active"
    from_to = []
    type = "account_receivable"
    sub_type = "contribution"
    supports_advanced_criteria = False

    @classmethod
    def get_linked_class(cls, sender, class_name, **kwargs):
        return ["Insuree"] if class_name == "SPHolder" else []

    @classmethod
    def get_parameters(cls, sender, class_name, instance, **kwargs):
        return [PARAM] if class_name == "SPHolder" and instance is not None else None

    @classmethod
    def check_calculation(cls, instance):
        return True

    @classmethod
    def active_for_object(cls, instance, context, type=None, sub_type=None):
        return True

    @classmethod
    def calculate(cls, instance, *args, **kwargs):
        return {}

    @classmethod
    def convert(cls, instance, convert_to, **kwargs):
        return {}


@override_settings(ROW_SECURITY=True)
class CalculationParamsScopeTest(openIMISGraphQLTestCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.original_rules = CALCULATION_RULES.copy()
        CALCULATION_RULES.clear()
        CALCULATION_RULES.append(SecurityParityRule)
        SecurityParityRule.signal_get_param.connect(SecurityParityRule.get_parameters, dispatch_uid="sp_param")
        SecurityParityRule.signal_get_linked_class.connect(
            SecurityParityRule.get_linked_class, dispatch_uid="sp_linked_class")

    @classmethod
    def tearDownClass(cls):
        SecurityParityRule.signal_get_param.disconnect(dispatch_uid="sp_param")
        SecurityParityRule.signal_get_linked_class.disconnect(dispatch_uid="sp_linked_class")
        CALCULATION_RULES.clear()
        CALCULATION_RULES.extend(cls.original_rules)
        super().tearDownClass()

    @classmethod
    def setUpTestData(cls):
        cls.t = create_security_tree("CLC")
        for key, village in (("a", cls.t.v1), ("b", cls.t.v2)):
            insuree = create_test_insuree(
                with_family=True, is_head=True,
                custom_props={"chf_id": f"CLC0000{1 if key == 'a' else 2}", "current_village": village},
                family_custom_props={"location": village})
            setattr(cls, f"ins_{key}", insuree)
        cls.user = create_right_only_user(
            "clcspuser", perm_ids(CalculationConfig.gql_query_calculation_rule_perms), [cls.t.d1.id])
        cls.token = get_test_token(cls.user)

    def setUp(self):
        cache.clear()

    def _params(self, instance_class_name, instance_id, class_name="SPHolder"):
        query = (f'{{ calculationParams(className: "{class_name}", instanceClassName: "{instance_class_name}", '
                 f'instanceId: "{instance_id}") {{ calculationParams {{ name }} }} }}')
        content = json.loads(self.query(query, headers={"HTTP_AUTHORIZATION": f"Bearer {self.token}"}).content)
        self.assertNotIn("errors", content, content.get("errors"))
        return [p["name"] for p in content["data"]["calculationParams"]["calculationParams"]]

    def test_linked_instance_in_scope(self):
        self.assertEqual(["sp_rate"], self._params("Insuree", self.ins_a.id))

    def test_linked_instance_out_of_scope_not_loaded(self):
        self.assertEqual([], self._params("Insuree", self.ins_b.id))

    def test_class_not_linked_by_the_rules_not_loaded(self):
        # any model could be loaded by its content type name and a client id
        self.assertEqual([], self._params("InteractiveUser", self.user.i_user.id))
        self.assertEqual([], self._params("Location", self.t.v2.id))
        # the link is per className: Insuree is linked to SPHolder only
        self.assertEqual([], self._params("Insuree", self.ins_a.id, class_name="Other"))

    def test_unknown_class_or_id(self):
        self.assertEqual([], self._params("NoSuchModel", "1"))
        self.assertEqual([], self._params("Insuree", "not-an-id"))
