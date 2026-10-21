"""Scenario: anatomy tutor for clinical reasoning (generic textbook anatomy)."""

from __future__ import annotations

from ..profiles import AgentRole, CapabilityProfile
from ..scenario import ControllerPolicy, KnowledgeItem, Scenario, Task

K = KnowledgeItem
KNOWLEDGE = [
    K(id="anatomy", text="Human anatomy organised for clinical reasoning", meta={"domain": "anatomy"}),
    K(
        id="msk",
        text="Musculoskeletal system: joints, muscles and their clinical injuries",
        parent="anatomy",
        meta={"domain": "musculoskeletal"},
    ),
    K(id="shoulder", text="Shoulder: glenohumeral joint stabilised by the rotator cuff", parent="msk"),
    K(
        id="cuff",
        text="Rotator cuff muscles: supraspinatus, infraspinatus, teres minor and subscapularis (SITS)",
        parent="shoulder",
    ),
    K(
        id="supra",
        text="Supraspinatus initiates abduction and is the most commonly torn rotator cuff tendon",
        parent="cuff",
    ),
    K(
        id="knee",
        text="Knee: hinge joint with cruciate and collateral ligaments and the menisci",
        parent="msk",
    ),
    K(
        id="acl",
        text="The anterior cruciate ligament (ACL) prevents anterior tibial translation; it tears in pivoting injuries with a pop and rapid swelling",
        parent="knee",
    ),
    K(
        id="meniscus",
        text="Menisci distribute load; medial meniscus tears cause joint-line tenderness and locking",
        parent="knee",
    ),
    K(
        id="hip",
        text="Hip: ball-and-socket joint; the gluteus medius abducts and stabilises the pelvis in stance",
        parent="msk",
    ),
    K(
        id="trendelenburg",
        text="Gluteus medius weakness produces a Trendelenburg sign: the pelvis drops on the opposite side when standing on one leg",
        parent="hip",
    ),
    K(
        id="cv",
        text="Cardiovascular system: heart, coronary arteries and great vessels",
        parent="anatomy",
        meta={"domain": "cardiovascular"},
    ),
    K(
        id="coronaries",
        text="The left coronary artery divides into the left anterior descending and circumflex; the right coronary supplies the sinoatrial node in most people",
        parent="cv",
    ),
    K(
        id="lad",
        text="Left anterior descending occlusion causes anterior myocardial infarction with ST elevation in leads V1-V4",
        parent="coronaries",
    ),
    K(
        id="valves",
        text="Heart valves: mitral and tricuspid close in systole producing the first heart sound; aortic and pulmonary close in diastole",
        parent="cv",
    ),
    K(
        id="nervous",
        text="Nervous system: peripheral nerves and plexuses",
        parent="anatomy",
        meta={"domain": "nervous"},
    ),
    K(
        id="brachial",
        text="Brachial plexus: roots C5-T1 form trunks, divisions, cords and branches",
        parent="nervous",
    ),
    K(
        id="erb",
        text="Upper trunk injury (C5-C6) causes Erb's palsy: adducted, internally rotated arm with extended elbow, the waiter's tip posture",
        parent="brachial",
    ),
    K(
        id="median",
        text="The median nerve passes through the carpal tunnel; compression causes numbness in the lateral three and a half digits",
        parent="brachial",
    ),
    K(
        id="sciatic",
        text="The sciatic nerve (L4-S3) exits below piriformis and divides into tibial and common fibular nerves",
        parent="nervous",
    ),
    K(
        id="fibular",
        text="Common fibular nerve injury at the fibular neck causes foot drop and loss of dorsiflexion",
        parent="sciatic",
    ),
    K(id="cases", text="Teaching cases", parent="anatomy", meta={"domain": "cases"}),
    K(
        id="case1",
        text="Case: 22-year-old footballer, pivoting injury, heard a pop, knee swollen within an hour",
        parent="cases",
        days_ago=2,
    ),
    K(
        id="case2",
        text="Case: 60-year-old with painful arc on abduction and weakness initiating abduction",
        parent="cases",
        days_ago=9,
    ),
    K(
        id="case3",
        text="Case: newborn after difficult delivery holding the arm in waiter's tip posture",
        parent="cases",
        days_ago=20,
    ),
]
PROFILES = [
    CapabilityProfile(
        name="tutor-model",
        provider="provider-a",
        domains=["musculoskeletal", "cardiovascular", "nervous"],
        reasoning=0.85,
        creativity=0.6,
        reliability=0.8,
        cost_per_call=1.0,
        latency_s=1.5,
    ),
    CapabilityProfile(
        name="case-model",
        provider="provider-b",
        domains=["cases"],
        reasoning=0.7,
        creativity=0.5,
        reliability=0.9,
        cost_per_call=0.5,
        latency_s=0.5,
    ),
]
ROLES = [
    AgentRole(
        name="anatomist",
        description="Anatomy tutor",
        system_prompt="You are an anatomy tutor. Explain structure and function from the records; cite record ids.",
        domains=["musculoskeletal", "cardiovascular", "nervous"],
        profile="tutor-model",
    ),
    AgentRole(
        name="clinician",
        description="Clinical correlator",
        system_prompt="You relate anatomy to clinical presentations from the records; cite record ids.",
        domains=["cases", "musculoskeletal", "nervous", "cardiovascular"],
        profile="case-model",
    ),
]
TASKS = [
    Task(
        question="Which rotator cuff muscle is most often torn and why does the patient struggle to start abduction?",
        expected_facets=["supraspinatus", "abduction"],
    ),
    Task(
        question="Explain the mechanism of ACL injury and the typical presentation.",
        expected_facets=["anterior cruciate", "pop"],
    ),
    Task(
        question="A newborn holds the arm in waiter's tip posture; which roots are injured?",
        expected_facets=["C5", "Erb"],
    ),
    Task(
        question="Compare the territories of the left anterior descending and the right coronary artery.",
        expected_facets=["left anterior descending", "right coronary"],
    ),
]
SCENARIO = Scenario(
    name="clinical_anatomy",
    title="Clinical anatomy tutor",
    description="Hierarchical anatomy with clinical correlations and recent teaching cases.",
    knowledge=KNOWLEDGE,
    profiles=PROFILES,
    roles=ROLES,
    tasks=TASKS,
    policy=ControllerPolicy(max_subtasks=3, total_budget=4.0, decay="none"),
)
