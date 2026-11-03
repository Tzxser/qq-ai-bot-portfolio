from dataclasses import dataclass


@dataclass(frozen=True)
class DepartmentRole:
    role_key: str
    display_name: str
    duty_status: str = "unconfirmed"
    scope: str = ""
    contact_ids: tuple[str, ...] = ()
    public_label: str = ""
    notify_enabled: bool = False
    duty_hours: str | None = None
    valid_until: str | None = None


ROLE_DEFINITIONS = (
    DepartmentRole("competition", "竞赛部", scope="算法学习、训练内容、代码答疑和备赛技术", public_label="竞赛部"),
    DepartmentRole("events", "赛事部", scope="比赛通知、报名流程、赛程和参赛资料", public_label="赛事部"),
    DepartmentRole("affairs", "事务部", scope="入会流程、群规、活动组织、场地和材料", public_label="事务部"),
    DepartmentRole("league_secretary", "社团团支书", scope="团务通知、主题活动及相关材料", public_label="社团团支书"),
    DepartmentRole("president", "会长", scope="社团总体事务、跨部门协调和需要决策的问题", public_label="会长"),
    DepartmentRole("association_lead", "协会负责人", scope="成员明确要求负责人本人回应时的原群转接", public_label="协会负责人"),
)


class DepartmentDirectory:
    """A small, reviewable directory; unknown contacts remain empty."""

    def __init__(self, settings):
        self.settings = settings
        target = str(getattr(settings, "association_lead_target_qq", "") or "")
        if target and (not target.isdecimal() or int(target) <= 0):
            raise ValueError("invalid association lead target")
        self.roles = list(ROLE_DEFINITIONS)
        if target:
            index = next(i for i, role in enumerate(self.roles) if role.role_key == "association_lead")
            role = self.roles[index]
            self.roles[index] = DepartmentRole(
                role.role_key, role.display_name, "configured", role.scope,
                (target,), role.public_label, True, role.duty_hours, role.valid_until,
            )

    def get(self, role_key):
        return next((role for role in self.roles if role.role_key == role_key), None)

    def association_lead(self):
        role = self.get("association_lead")
        if role is None or len(role.contact_ids) > 1:
            raise ValueError("association lead must be a singleton")
        return role

    def navigation(self):
        return "部门分流建议：算法训练和代码答疑可先联系竞赛部；比赛报名与赛程可先联系赛事部；入会、群规和材料可先联系事务部。团务、整体事务和负责人事项请向对应管理确认。"
