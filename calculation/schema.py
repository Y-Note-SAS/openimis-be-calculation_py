import graphene
from .apps import CALCULATION_RULES, CalculationConfig
from .services import get_rule_name, get_parameters, get_linked_class
from django.contrib.contenttypes.models import ContentType
from django.core.exceptions import ValidationError
from core.models.row_security import target_queryset


class CalculationRulesGQLType(graphene.ObjectType):
    calculation_class_name = graphene.String()
    status = graphene.String()
    description = graphene.String()
    uuid = graphene.UUID()
    class_param = graphene.JSONString()
    date_valid_from = graphene.Date()
    date_valid_to = graphene.Date()
    from_to = graphene.JSONString()
    type = graphene.String()
    sub_type = graphene.String()


class CalculationRulesListGQLType(graphene.ObjectType):
    calculation_rules = graphene.List(CalculationRulesGQLType)


class LabelParamGQLType(graphene.ObjectType):
    en = graphene.String()
    fr = graphene.String()


class RightParamGQLType(graphene.ObjectType):
    read = graphene.String()
    write = graphene.String()
    update = graphene.String()
    replace = graphene.String()


class OptionParamGQLType(graphene.ObjectType):
    value = graphene.String()
    label = graphene.Field(LabelParamGQLType)


class CalculationParamsGQLType(graphene.ObjectType):
    type = graphene.String()
    name = graphene.String()
    label = graphene.Field(LabelParamGQLType)
    rights = graphene.Field(RightParamGQLType)
    option_set = graphene.List(OptionParamGQLType)
    relevance = graphene.String()
    required = graphene.String()
    condition = graphene.String()
    default_value = graphene.String()


class CalculationParamsListGQLType(graphene.ObjectType):
    calculation_params = graphene.List(CalculationParamsGQLType)


class LinkedClassListGQLType(graphene.ObjectType):
    linked_classes = graphene.List(graphene.String)


class Query(graphene.ObjectType):

    calculation_rules_by_class_name = graphene.Field(
        CalculationRulesListGQLType,
        class_name=graphene.Argument(graphene.String, required=True),
    )

    calculation_rules = graphene.Field(
        CalculationRulesListGQLType,
        calculation=graphene.Argument(graphene.UUID, required=False),
        calcrule_type=graphene.Argument(graphene.String, required=False),
    )

    calculation_params = graphene.Field(
        CalculationParamsListGQLType,
        class_name=graphene.Argument(graphene.String, required=True),
        instance_id=graphene.Argument(graphene.String, required=True),
        instance_class_name=graphene.Argument(graphene.String, required=True),
    )

    linked_class = graphene.Field(
        LinkedClassListGQLType,
        class_name_list=graphene.Argument(graphene.List(graphene.String), required=False),
    )

    def resolve_calculation_rules_by_class_name(parent, info, **kwargs):
        if not info.context.user.has_perms(CalculationConfig.gql_query_calculation_rule_perms):
           raise PermissionError("Unauthorized")

        class_name = kwargs.get("class_name", None)
        list_cr = []
        if class_name:
            list_signal_result = get_rule_name(class_name=class_name)
            if list_signal_result:
                for sr in list_signal_result:
                    # get the signal result - calculation rule object
                    #  related to the input class name
                    rule = sr[1]
                    if rule:
                        list_cr.append(
                            CalculationRulesGQLType(
                                calculation_class_name=rule.calculation_rule_name,
                                status=rule.status,
                                description=rule.description,
                                uuid=rule.uuid,
                                class_param=rule.impacted_class_parameter,
                                date_valid_from=rule.date_valid_from,
                                date_valid_to=rule.date_valid_to,
                                from_to=rule.from_to,
                                type=rule.type,
                                sub_type=rule.sub_type
                            )
                        )
        return CalculationRulesListGQLType(list_cr)

    def resolve_calculation_rules(parent, info, **kwargs):
        if not info.context.user.has_perms(CalculationConfig.gql_query_calculation_rule_perms):
            raise PermissionError("Unauthorized")

        calculation = kwargs.get("calculation", None)
        calcrule_type = kwargs.get("calcrule_type", None)

        if calculation or calcrule_type:
            list_cr = []
            for cr in CALCULATION_RULES:
                calculation = f'{calculation}'
                if (cr.uuid == calculation and calcrule_type == cr.type) \
                        or (cr.uuid == calculation and calcrule_type is None) \
                        or (calculation == 'None' and calcrule_type == cr.type):
                    list_cr = _append_to_calcrule_list(list_cr, cr)
        else:
            list_cr = []
            for cr in CALCULATION_RULES:
                list_cr = _append_to_calcrule_list(list_cr, cr)

        return CalculationRulesListGQLType(list_cr)

    def resolve_calculation_params(parent, info, **kwargs):
        if not info.context.user.has_perms(CalculationConfig.gql_query_calculation_rule_perms):
           raise PermissionError("Unauthorized")

        # get the obligatory params from query
        class_name = kwargs.get("class_name", None)
        instance_id = kwargs.get("instance_id", None)
        instance_class_name = kwargs.get("instance_class_name", None)

        instance = None
        # if calculation class - it is not a model
        if instance_class_name == "Calculation":
            for calculation_rule in CALCULATION_RULES:
                if calculation_rule.uuid == instance_id:
                    instance = calculation_rule
        else:
            # only a class the rules link to `class_name`, and only a row the user may read
            instance = get_linked_instance(info.context.user, class_name, instance_class_name, instance_id)

        list_params = []
        if class_name and instance:
            # use service to send signal to all class to obtain params related to the instance
            list_signal_result = get_parameters(class_name=class_name, instance=instance)
            tranformed_signal_results = []
            if list_signal_result:
                for sr in list_signal_result:
                    # get the signal result - calculation param object
                    #  related to the input class name and instance
                    # do not include None results
                    if sr[1]:
                        tranformed_signal_results.extend(sr[1])
            # make parameter list from signal unique - discinct list of dict by 'name' keyword
            tranformed_signal_results = list({v['name']: v for v in tranformed_signal_results}.values())
            for param in tranformed_signal_results:
                rights = RightParamGQLType(
                    read=param['rights']['read'] if 'read' in param['rights'] else None,
                    write=param['rights']['write'] if 'write' in param['rights'] else None,
                    update=param['rights']['update'] if 'update' in param['rights'] else None,
                    replace=param['rights']['replace'] if 'replace' in param['rights'] else None,
                )
                #FIXME, either rely on locals (BEST case) or manage it generically
                label = LabelParamGQLType(
                    en=param['label']['en'] if 'en' in param['label'] else None,
                    fr=param['label']['fr'] if 'fr' in param['label'] else None,
                )
                option_set = [OptionParamGQLType(
                    value=ov["value"],
                    label=LabelParamGQLType(en=ov["label"]["en"], fr=ov["label"]["fr"])
                ) for ov in param["optionSet"]] if "optionSet" in param else []

                if "condition" in param:
                    condition = param["condition"] if param["condition"] else None
                else:
                    condition = None
                if "relevance" in param:
                    relevance = param["relevance"] if param["relevance"] else None
                else:
                    relevance = None
 
                list_params.append(
                    CalculationParamsGQLType(
                        type=param['type'],
                        name=param['name'],
                        label=label,
                        rights=rights,
                        option_set=option_set,
                        relevance=relevance,
                        condition=condition,
                        default_value=param['default'] if 'default' in param else "null",
                    )
                )
        return CalculationParamsListGQLType(list_params)

    def resolve_linked_class(parent, info, **kwargs):
        if not info.context.user.has_perms(CalculationConfig.gql_query_calculation_rule_perms):
           raise PermissionError("Unauthorized")
        result_linked_class = []
        # get the params from query
        class_name_list = kwargs.get("class_name_list", None)
        list_signal_result = get_linked_class(class_name_list=class_name_list)
        for sr in list_signal_result:
            if sr[1]:
                result_linked_class = result_linked_class + sr[1]
        result_linked_class = list(set(result_linked_class))
        # remove product when we have PaymentPlan/ContributionPlan object
        # TODO: find a more generic way to avoid loop cause by relationship objects (product-calcule) 
        if 'PaymentPlan' in class_name_list or 'ContributionPlan' in class_name_list:
            if 'Product' in result_linked_class:
                result_linked_class.remove('Product')
        return LinkedClassListGQLType(result_linked_class)


def allowed_instance_classes(class_name):
    """
    The classes (lower case) whose instance may carry the calculation parameters of
    `class_name`: the ones the calculation rules link to it (get_linked_class). Any
    other model is not loaded at all.
    """
    if not class_name:
        return set()
    # on this release get_linked_class gives the signal results: (receiver, [class names])
    return {
        name.lower()
        for _receiver, names in get_linked_class(class_name_list=[class_name])
        for name in (names or []) if name
    }


def get_linked_instance(user, class_name, instance_class_name, instance_id):
    """
    The `instance_class_name` row `instance_id`, when the rules link that class to
    `class_name` and `user` may read the row (the model's row security, through core
    target_queryset); None otherwise, whatever the reason, so the query does not tell
    a refused row from a missing one.
    """
    if not instance_class_name or not instance_id:
        return None
    if instance_class_name.lower() not in allowed_instance_classes(class_name):
        return None
    instance_type = ContentType.objects.filter(model__iexact=instance_class_name).first()
    instance_class = instance_type.model_class() if instance_type else None
    if instance_class is None:
        return None
    try:
        return target_queryset(instance_class, user).filter(pk=instance_id).first()
    except (ValueError, TypeError, ValidationError):
        # not an id of that model
        return None


def _append_to_calcrule_list(list_cr, cr):
    list_cr.append(
        CalculationRulesGQLType(
            calculation_class_name=cr.calculation_rule_name,
            status=cr.status,
            description=cr.description,
            uuid=cr.uuid,
            class_param=cr.impacted_class_parameter,
            date_valid_from=cr.date_valid_from,
            date_valid_to=cr.date_valid_to,
            from_to=cr.from_to,
            type=cr.type,
            sub_type=cr.sub_type
        )
    )
    return list_cr
