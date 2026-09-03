from __future__ import annotations

from pathlib import Path
import sys
import unittest
from unittest import mock


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from afe2_catalogue.collection import (  # noqa: E402
    CollectionFormatError,
    build_collection_document,
    build_kit_membership_index,
    build_progression_perk_index,
    collection_product_package_paths,
    collection_wrapper_dependency_paths,
    kit_reward_registry_dependency_paths,
    kit_reward_table_dependency_paths,
    kit_reward_table_package_paths,
    progression_reward_table_dependency_paths,
    progression_reward_table_package_paths,
)
from afe2_catalogue import semantic_assets  # noqa: E402


STORE = "/Game/Blueprints/Stores/Store_MainHub_Credits"
WEAPON = "/Game/Weapons/Weapon_Visible"
PACK = "/Game/Rewards/Pack_Augment"
TABLE = "/Game/Rewards/Table_Augment"
AUGMENT_A = "/Game/Augments/Augment_A"
AUGMENT_B = "/Game/Augments/Augment_B"
STALE_TABLE = "/Game/Rewards/Stale_Default_Table"
ITEM = "/Game/Items/Item_Major"
PERK = "/Game/Perks/Perk_Visible"
PROGRESSION_SETTINGS = "/Game/Design/Rewards/RewardTable_Settings_V1"
PROGRESSION_ROOT = "/Game/Rewards/Progression_Root"
PROGRESSION_NESTED = "/Game/Rewards/Progression_Nested"
PROGRESSION_MISSING = "/Game/Rewards/Progression_Missing"
PROGRESSION_STALE = "/Game/Rewards/Progression_Stale"
PROGRESSION_PARENT = "/Game/Rewards/Progression_Parent"
PROGRESSION_CHILD = "/Game/Rewards/Progression_Child"
PROGRESSION_PERK = "/Game/Perks/Perk_Progression"
PROGRESSION_NON_PERK = "/Game/Items/Item_Progression"
DEFAULT_STARTING = "/Game/Design/Rewards/DefaultStarting_Rewards"
KIT_REGISTRY = "/Game/Metagame/AchievementMetaMissions"
KIT_REWARD = "/Game/Rewards/Unlock_Future_Class"
KIT_REWARD_PARENT = "/Game/Rewards/Unlock_Future_Class_Parent"
KIT_NON_REWARD = "/Game/Metagame/Special/MM_Future_Class"
CLASS_STARTING = "/Game/Classes/Player_Starting"
CLASS_FUTURE = "/Game/Classes/Player_Future"
CLASS_LATENT = "/Game/Classes/Player_Latent"
KIT_STARTING = "/Game/ClassUnlocks/KitUnlock_Starting"
KIT_FUTURE = "/Game/ClassUnlocks/KitUnlock_Future"
KIT_LATENT = "/Game/ClassUnlocks/KitUnlock_Latent"
CHARACTER_UNLOCK_TOKEN = "/Script/Endeavor.CharacterUnlockToken"


def prop(
    name: str,
    value: object,
    type_name: str = "ObjectPropertyData",
    **extra: object,
) -> dict[str, object]:
    return {"$type": type_name, "Name": name, "Value": value, **extra}


def soft_value(package: str) -> dict[str, object]:
    return {
        "AssetPath": {
            "PackageName": None,
            "AssetName": f"{package}.{package.rsplit('/', 1)[-1]}_C",
        },
        "SubPathString": None,
    }


def soft(name: str, package: str) -> dict[str, object]:
    return prop(name, soft_value(package), "SoftObjectPropertyData")


def enum(name: str, value: str) -> dict[str, object]:
    return prop(name, None, "EnumPropertyData", EnumValue=value)


def text(name: str, value: str) -> dict[str, object]:
    return prop(
        name,
        "LOCALIZATION_KEY",
        "TextPropertyData",
        CultureInvariantString=value,
        HistoryType="Base",
    )


def asset(package: str, data: list[dict[str, object]]) -> dict[str, object]:
    return {
        "packagePath": package,
        "imports": [],
        "exports": [{"objectName": f"Default__{package.rsplit('/', 1)[-1]}_C", "data": data}],
    }


def product(product_type: str, field: str, package: str) -> dict[str, object]:
    return prop(
        "Product",
        [
            enum("ProductType", f"ESimpleCraftingRecipeProductType::{product_type}"),
            soft(field, package),
            prop("Count", 1, "IntPropertyData"),
            prop("bPermaUnlock", False, "BoolPropertyData"),
            prop("bSkipAutoSlot", False, "BoolPropertyData"),
            prop("bCanReceive", False, "BoolPropertyData"),
        ],
        "StructPropertyData",
    )


def sold_item(product_value: dict[str, object], *, purchasable: bool = True) -> dict[str, object]:
    return prop(
        "SoldItems",
        [
            product_value,
            enum("FeatureUnlockRequirement", "EFeatureUnlocks::None"),
            prop("Cost", 2500, "IntPropertyData"),
            prop("Purchasable", purchasable, "BoolPropertyData"),
        ],
        "StructPropertyData",
    )


def category(key: str, display_name: str, entries: list[dict[str, object]]) -> dict[str, object]:
    return prop(
        "Categories",
        [
            prop("Category", key, "StrPropertyData"),
            text("DisplayName", display_name),
            prop("SoldItems", entries, "ArrayPropertyData"),
        ],
        "StructPropertyData",
    )


def store_asset() -> dict[str, object]:
    return asset(
        STORE,
        [
            prop(
                "Categories",
                [
                    category(
                        "Weapons",
                        "Weapons",
                        [sold_item(product("Gun", "GunUnlockClass", WEAPON))],
                    ),
                    category(
                        "AugmentPacks",
                        "Augments",
                        [sold_item(product("Droppable", "ItemClass", PACK), purchasable=False)],
                    ),
                    category(
                        "Items",
                        "Items",
                        [sold_item(product("Droppable", "ItemClass", ITEM))],
                    ),
                    category(
                        "Perks",
                        "Perks",
                        [
                            sold_item(product("Droppable", "ItemClass", PERK)),
                            sold_item(product("Droppable", "ItemClass", PERK), purchasable=False),
                        ],
                    ),
                    category(
                        "Challenge Cards",
                        "Challenge Cards",
                        [sold_item(product("Droppable", "ItemClass", "/Game/Ignored/Card"))],
                    ),
                ],
                "ArrayPropertyData",
            )
        ],
    )


def reward_row(package: str) -> dict[str, object]:
    return prop(
        "Rewards",
        [
            prop("Reward", [soft("Droppable", package)], "StructPropertyData"),
            enum("RewardType", "ERewardEntry::Droppable"),
            # This native-default field is deliberately populated.  The
            # discriminant says Droppable, so it must never be traversed.
            soft("RewardTable", STALE_TABLE),
        ],
        "StructPropertyData",
    )


def augment_pack() -> dict[str, object]:
    return asset(PACK, [soft("RewardTable", TABLE), text("Name", "Example augment")])


def augment_table() -> dict[str, object]:
    return asset(
        TABLE,
        [
            prop(
                "RewardTable",
                [
                    prop(
                        "Rewards",
                        [reward_row(AUGMENT_B), reward_row(AUGMENT_A)],
                        "ArrayPropertyData",
                    )
                ],
                "StructPropertyData",
            )
        ],
    )


def item_asset(tier: str = "Major") -> dict[str, object]:
    tag_property = prop(
        "Tags",
        [
            prop(
                "Tags",
                [f"Ability.Consumable.InventoryType.{tier}", "Ability.Consumable.Combat"],
                "GameplayTagContainerPropertyData",
            )
        ],
        "StructPropertyData",
    )
    return asset(ITEM, [text("Name", "Item"), tag_property])


def progression_settings(
    roots: list[str],
    *,
    objective: str = "Synthetic Objective",
) -> dict[str, object]:
    unlock_value = prop(
        "UnlockRewardTablesMap",
        [
            prop(
                "RewardTables",
                [soft(str(index), package) for index, package in enumerate(roots)],
                "ArrayPropertyData",
            ),
            text("UnlockDescription", 'Completing mission: "{objective}"'),
        ],
        "StructPropertyData",
    )
    unlock_map = prop(
        "UnlockRewardTablesMap",
        [
            [
                prop("UnlockRewardTablesMap", "Mission", "NamePropertyData"),
                unlock_value,
            ]
        ],
        "MapPropertyData",
    )
    objective_map = prop(
        "RewardTableObjectivesMap",
        [[soft("RewardTableObjectivesMap", roots[0]), text("Objective", objective)]],
        "MapPropertyData",
    )
    return asset(PROGRESSION_SETTINGS, [unlock_map, objective_map])


def progression_reward_row(
    reward_type: str,
    target: str,
    *,
    imported_table: bool = False,
    stale_table: str | None = None,
) -> dict[str, object]:
    reward = prop(
        "Reward",
        [
            soft(
                "Droppable",
                target if reward_type == "Droppable" else PROGRESSION_NON_PERK,
            ),
            prop("Count", 1, "IntPropertyData"),
            prop("MinCount", 1, "IntPropertyData"),
            prop("MaxCount", 1, "IntPropertyData"),
            prop("Level", 1, "IntPropertyData"),
            prop("bShowAsPostGameReward", True, "BoolPropertyData"),
            prop("AlternativeCashRewardCount", 1000, "IntPropertyData"),
        ],
        "StructPropertyData",
    )
    table_reference = (
        prop("RewardTable", -2, "ObjectPropertyData")
        if imported_table
        else soft("RewardTable", stale_table or target)
    )
    return prop(
        "Rewards",
        [
            prop("Chance", 1.0, "FloatPropertyData"),
            reward,
            prop(
                "RewardType",
                None,
                "BytePropertyData",
                EnumValue=f"ERewardEntry::{reward_type}",
            ),
            table_reference,
            prop("MinLevel", 1, "IntPropertyData"),
            prop("MaxLevel", 0, "IntPropertyData"),
            prop("bShowAsPostGameReward", True, "BoolPropertyData"),
            enum("RequiredFeatureUnlock", "EFeatureUnlocks::None"),
        ],
        "StructPropertyData",
    )


def progression_table(
    package: str,
    rows: list[dict[str, object]],
) -> dict[str, object]:
    return asset(
        package,
        [
            prop(
                "RewardTable",
                [prop("Rewards", rows, "ArrayPropertyData")],
                "StructPropertyData",
            )
        ],
    )


def imported_nested_progression_table() -> dict[str, object]:
    value = progression_table(
        PROGRESSION_ROOT,
        [
            progression_reward_row(
                "RewardTable",
                PROGRESSION_NESTED,
                imported_table=True,
            ),
            progression_reward_row(
                "Droppable",
                PROGRESSION_NON_PERK,
                stale_table=PROGRESSION_STALE,
            ),
        ],
    )
    value["imports"] = [
        {
            "objectName": PROGRESSION_NESTED,
            "outerIndex": 0,
        },
        {
            "objectName": "Progression_Nested_C",
            "outerIndex": -1,
        },
    ]
    return value


def inherited_progression_table() -> dict[str, object]:
    return {
        "packagePath": PROGRESSION_CHILD,
        "imports": [
            {"objectName": PROGRESSION_PARENT, "outerIndex": 0},
            {"objectName": "Progression_Parent_C", "outerIndex": -1},
        ],
        "exports": [
            {
                "objectName": "Progression_Child_C",
                "superIndex": -2,
                "type": "ClassExport",
                "data": [],
            },
            {"objectName": "Default__Progression_Child_C", "data": []},
        ],
    }


def character_unlock_row(
    class_package: str,
    *,
    selected_token: str = CHARACTER_UNLOCK_TOKEN,
) -> dict[str, object]:
    return prop(
        "Rewards",
        [
            prop(
                "Reward",
                [
                    prop(
                        "Droppable",
                        {
                            "AssetPath": {
                                "AssetName": selected_token,
                                "PackageName": None,
                            },
                            "SubPathString": None,
                        },
                        "SoftObjectPropertyData",
                    ),
                    soft("CharacterUnlock", class_package),
                    soft("GunUnlock", "None"),
                ],
                "StructPropertyData",
            ),
            prop(
                "RewardType",
                None,
                "BytePropertyData",
                EnumValue="ERewardEntry::Droppable",
            ),
        ],
        "StructPropertyData",
    )


def kit_reward_table(package: str, rows: list[dict[str, object]]) -> dict[str, object]:
    return progression_table(package, rows)


def kit_registry() -> dict[str, object]:
    value = asset(KIT_REGISTRY, [])
    value["imports"] = [
        {
            "className": "Unlock_Future_Class_C",
            "classPackage": KIT_REWARD,
            "objectName": "Default__Unlock_Future_Class_C",
            "outerIndex": -2,
        },
        {
            "className": "MM_Future_Class_C",
            "classPackage": KIT_NON_REWARD,
            "objectName": "Default__MM_Future_Class_C",
            "outerIndex": -4,
        },
        {
            "className": "Package",
            "classPackage": "/Script/CoreUObject",
            "objectName": KIT_REWARD,
            "outerIndex": 0,
        },
        {
            "className": "Package",
            "classPackage": "/Script/CoreUObject",
            "objectName": KIT_NON_REWARD,
            "outerIndex": 0,
        },
    ]
    return value


def kit_record(record_id: str, class_package: str) -> dict[str, str]:
    return {
        "characterClassPackagePath": class_package,
        "id": record_id,
        "kind": "kit",
        "packagePath": record_id,
    }


def candidates() -> list[dict[str, str]]:
    return [
        {"id": WEAPON, "kind": "weapon", "packagePath": WEAPON},
        {"id": AUGMENT_A, "kind": "augment", "packagePath": AUGMENT_A},
        {"id": AUGMENT_B, "kind": "augment", "packagePath": AUGMENT_B},
        {"id": PERK, "kind": "perk", "packagePath": PERK},
    ]


class CollectionTests(unittest.TestCase):
    def build(self, **overrides: object) -> dict[str, object]:
        arguments: dict[str, object] = {
            "store_asset": store_asset(),
            "wrapper_assets": [augment_pack(), augment_table()],
            "terminal_assets": [item_asset()],
            "candidate_records": candidates(),
            "source_fingerprint": "sha256:test",
        }
        arguments.update(overrides)
        return build_collection_document(**arguments)  # type: ignore[arg-type]

    def test_discovers_first_hop_products_for_only_planner_categories(self) -> None:
        self.assertEqual(
            collection_product_package_paths(store_asset()),
            tuple(sorted({WEAPON, PACK, ITEM, PERK})),
        )

    def test_discovers_only_discriminant_selected_wrapper_dependencies(self) -> None:
        self.assertEqual(collection_wrapper_dependency_paths([augment_pack()]), (TABLE,))
        self.assertEqual(
            collection_wrapper_dependency_paths([augment_table()]),
            (AUGMENT_A, AUGMENT_B),
        )

    def test_builds_direct_wrapped_and_item_membership(self) -> None:
        document = self.build()
        self.assertEqual(document["status"], "complete")
        self.assertEqual(document["coverage"]["categories"], 4)
        self.assertEqual(
            document["categoryAudit"],
            {
                "ignoredKeys": ["Challenge Cards"],
                "includedKeys": ["AugmentPacks", "Items", "Perks", "Weapons"],
                "observedKeys": [
                    "AugmentPacks",
                    "Challenge Cards",
                    "Items",
                    "Perks",
                    "Weapons",
                ],
                "unknownKeys": [],
            },
        )
        self.assertEqual(document["coverage"]["ignoredCategories"], 1)
        self.assertEqual(document["coverage"]["unknownCategories"], 0)
        self.assertEqual(document["coverage"]["productRows"], 5)
        self.assertEqual(document["coverage"]["resolvedProductRows"], 5)

        by_key = {value["key"]: value for value in document["categories"]}
        augment = by_key["AugmentPacks"]["entries"][0]
        self.assertEqual(augment["id"], PACK)
        self.assertEqual(augment["wrapperPackagePaths"], [PACK, TABLE])
        self.assertEqual(
            [value["id"] for value in augment["terminalRecords"]],
            [AUGMENT_A, AUGMENT_B],
        )
        self.assertFalse(augment["availability"]["purchasable"])

        item = by_key["Items"]["entries"][0]["terminalRecords"][0]
        self.assertEqual(item["itemTier"], "major")
        self.assertEqual(by_key["Perks"]["memberIds"], [PERK])
        self.assertEqual(len(document["memberships"][PERK]), 2)
        self.assertEqual(document["memberships"][AUGMENT_A][0]["entryId"], PACK)

    def test_output_is_deterministic_when_dependency_inputs_are_reversed(self) -> None:
        first = self.build()
        second = self.build(
            wrapper_assets=[augment_table(), augment_pack()],
            terminal_assets=list(reversed([item_asset()])),
            candidate_records=list(reversed(candidates())),
        )
        self.assertEqual(first, second)

    def test_unknown_store_category_is_reported_without_becoming_selectable(self) -> None:
        source = store_asset()
        categories = source["exports"][0]["data"][0]["Value"]
        categories.append(
            category(
                "Experimental Attachments",
                "Experimental Attachments",
                [sold_item(product("Droppable", "ItemClass", "/Game/Unknown/Item"))],
            )
        )
        document = self.build(store_asset=source)
        self.assertEqual(
            document["categoryAudit"]["unknownKeys"],
            ["Experimental Attachments"],
        )
        self.assertEqual(document["coverage"]["unknownCategories"], 1)
        self.assertNotIn(
            "Experimental Attachments",
            {value["key"] for value in document["categories"]},
        )

    def test_missing_wrapper_dependency_fails_closed(self) -> None:
        document = self.build(wrapper_assets=[augment_pack()])
        by_key = {value["key"]: value for value in document["categories"]}
        augment = by_key["AugmentPacks"]["entries"][0]
        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(augment["status"], "unresolved")
        self.assertEqual(augment["terminalRecords"], [])
        self.assertEqual(by_key["AugmentPacks"]["memberIds"], [])
        self.assertEqual(document["coverage"]["unresolvedProductRows"], 1)
        self.assertEqual(document["unresolved"][0]["packagePath"], TABLE)

    def test_item_without_exactly_one_tier_tag_fails_closed(self) -> None:
        document = self.build(terminal_assets=[item_asset("Unknown")])
        by_key = {value["key"]: value for value in document["categories"]}
        self.assertEqual(by_key["Items"]["entries"][0]["status"], "unresolved")
        self.assertNotIn(ITEM, document["memberships"])

    def test_item_candidate_without_a_valid_tier_still_fails_closed(self) -> None:
        item_candidate = {"id": ITEM, "kind": "item", "packagePath": ITEM}
        document = self.build(
            candidate_records=[*candidates(), item_candidate],
            terminal_assets=[item_asset("Unknown")],
        )
        by_key = {value["key"]: value for value in document["categories"]}
        entry = by_key["Items"]["entries"][0]
        self.assertEqual(entry["status"], "unresolved")
        self.assertEqual(document["unresolved"][0]["reason"], "item-tier-unresolved")
        self.assertNotIn(ITEM, document["memberships"])

    def test_wrong_candidate_kind_fails_closed(self) -> None:
        wrong = [dict(value) for value in candidates()]
        wrong[0]["kind"] = "mod"
        document = self.build(candidate_records=wrong)
        by_key = {value["key"]: value for value in document["categories"]}
        self.assertEqual(by_key["Weapons"]["entries"][0]["status"], "unresolved")
        self.assertEqual(document["unresolved"][0]["reason"], "terminal-kind-mismatch")

    def test_malformed_store_is_rejected(self) -> None:
        with self.assertRaises(CollectionFormatError):
            self.build(store_asset=asset(STORE, []))


class KitMembershipTests(unittest.TestCase):
    def test_admits_only_classes_selected_by_authored_reward_sources(self) -> None:
        starting = kit_reward_table(
            DEFAULT_STARTING,
            [
                character_unlock_row(CLASS_STARTING),
                # A populated native-default CharacterUnlock is not selected
                # unless Droppable points at CharacterUnlockToken.
                character_unlock_row(
                    CLASS_LATENT,
                    selected_token="/Game/Items/Ordinary_Droppable",
                ),
            ],
        )
        registry = kit_registry()
        future_reward = kit_reward_table(
            KIT_REWARD,
            [character_unlock_row(CLASS_FUTURE)],
        )
        non_reward = asset(KIT_NON_REWARD, [prop("Objective", 2, "IntPropertyData")])
        kits = [
            kit_record(KIT_STARTING, CLASS_STARTING),
            kit_record(KIT_FUTURE, CLASS_FUTURE),
            kit_record(KIT_LATENT, CLASS_LATENT),
        ]

        self.assertEqual(
            kit_reward_registry_dependency_paths([registry]),
            (KIT_NON_REWARD, KIT_REWARD),
        )
        self.assertEqual(
            kit_reward_table_package_paths(
                registry_assets=[registry],
                referenced_assets=[non_reward, future_reward],
            ),
            (KIT_REWARD,),
        )
        self.assertEqual(
            kit_reward_table_dependency_paths(
                reward_table_assets=[starting, future_reward],
                root_package_paths=[DEFAULT_STARTING, KIT_REWARD],
            ),
            (),
        )

        document = build_kit_membership_index(
            starting_asset=starting,
            registry_assets=[registry],
            reward_table_assets=[future_reward, non_reward],
            kit_records=kits,
        )

        self.assertEqual(document["status"], "complete")
        self.assertEqual(document["memberIds"], [KIT_FUTURE, KIT_STARTING])
        self.assertNotIn(KIT_LATENT, document["memberIds"])
        self.assertEqual(document["coverage"]["authorizedCharacterClasses"], 2)
        self.assertEqual(document["coverage"]["excludedCandidateKits"], 1)
        sources = {
            entry["id"]: entry["sources"][0]["sourceKind"]
            for entry in document["entries"]
        }
        self.assertEqual(sources[KIT_STARTING], "default-starting-rewards")
        self.assertEqual(sources[KIT_FUTURE], "metamission-registry")

        reversed_document = build_kit_membership_index(
            starting_asset=starting,
            registry_assets=[registry],
            reward_table_assets=[non_reward, future_reward],
            kit_records=list(reversed(kits)),
        )
        self.assertEqual(document, reversed_document)

    def test_duplicate_character_to_kit_mapping_fails_closed(self) -> None:
        starting = kit_reward_table(
            DEFAULT_STARTING,
            [character_unlock_row(CLASS_STARTING)],
        )
        duplicate = kit_record("/Game/ClassUnlocks/KitUnlock_Duplicate", CLASS_STARTING)
        document = build_kit_membership_index(
            starting_asset=starting,
            registry_assets=[],
            reward_table_assets=[],
            kit_records=[kit_record(KIT_STARTING, CLASS_STARTING), duplicate],
        )

        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["memberIds"], [])
        self.assertEqual(
            document["unresolved"][0]["reason"],
            "authorized-character-class-mapped-to-multiple-kits",
        )

    def test_empty_default_starting_table_fails_closed(self) -> None:
        document = build_kit_membership_index(
            starting_asset=kit_reward_table(DEFAULT_STARTING, []),
            registry_assets=[],
            reward_table_assets=[],
            kit_records=[kit_record(KIT_STARTING, CLASS_STARTING)],
        )

        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["memberIds"], [])
        self.assertEqual(
            document["unresolved"][0]["reason"],
            "default-starting-rewards-had-no-character-unlocks",
        )

    def test_registry_reward_without_default_object_fails_closed(self) -> None:
        starting = kit_reward_table(
            DEFAULT_STARTING,
            [character_unlock_row(CLASS_STARTING)],
        )
        registry = kit_registry()
        child = {
            "packagePath": KIT_REWARD,
            "imports": [
                {"objectName": KIT_REWARD_PARENT, "outerIndex": 0},
                {"objectName": "Unlock_Future_Class_Parent_C", "outerIndex": -1},
            ],
            "exports": [
                {
                    "objectName": "Unlock_Future_Class_C",
                    "superIndex": -2,
                    "type": "ClassExport",
                    "data": [],
                }
            ],
        }
        parent = kit_reward_table(
            KIT_REWARD_PARENT,
            [character_unlock_row(CLASS_FUTURE)],
        )

        document = build_kit_membership_index(
            starting_asset=starting,
            registry_assets=[registry],
            reward_table_assets=[child, parent],
            kit_records=[
                kit_record(KIT_STARTING, CLASS_STARTING),
                kit_record(KIT_FUTURE, CLASS_FUTURE),
            ],
        )

        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["memberIds"], [KIT_STARTING])
        self.assertIn(
            "registry-imported-class-had-no-default-export",
            {problem["reason"] for problem in document["unresolved"]},
        )

    def test_malformed_registry_imports_fail_closed(self) -> None:
        starting = kit_reward_table(
            DEFAULT_STARTING,
            [character_unlock_row(CLASS_STARTING)],
        )
        registry = asset(KIT_REGISTRY, [])
        registry["imports"] = "not-an-import-array"

        document = build_kit_membership_index(
            starting_asset=starting,
            registry_assets=[registry],
            reward_table_assets=[],
            kit_records=[kit_record(KIT_STARTING, CLASS_STARTING)],
        )

        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["memberIds"], [KIT_STARTING])
        self.assertEqual(document["coverage"]["malformedRegistryImports"], 1)
        self.assertEqual(
            document["unresolved"][0]["reason"],
            "metamission-registry-imports-malformed",
        )

    def test_invalid_starting_source_keeps_root_coverage_without_duplicate_problem(self) -> None:
        document = build_kit_membership_index(
            starting_asset=asset(
                DEFAULT_STARTING,
                [prop("Objective", 1, "IntPropertyData")],
            ),
            registry_assets=[],
            reward_table_assets=[],
            kit_records=[kit_record(KIT_STARTING, CLASS_STARTING)],
        )

        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["coverage"]["rootTableReferences"], 1)
        self.assertEqual(document["coverage"]["unresolvedReferences"], 1)
        self.assertEqual(len(document["unresolved"]), 1)
        self.assertEqual(
            document["unresolved"][0]["reason"],
            "default-starting-source-was-not-reward-table",
        )


class ProgressionPerkTests(unittest.TestCase):
    def test_traverses_only_selected_reward_tables_and_indexes_perks(self) -> None:
        settings = progression_settings([PROGRESSION_ROOT, PROGRESSION_MISSING])
        root = imported_nested_progression_table()
        nested = progression_table(
            PROGRESSION_NESTED,
            [progression_reward_row("Droppable", PROGRESSION_PERK)],
        )
        candidate_records = [
            {"id": PROGRESSION_PERK, "kind": "perk", "packagePath": PROGRESSION_PERK},
            {
                "id": PROGRESSION_NON_PERK,
                "kind": "item",
                "packagePath": PROGRESSION_NON_PERK,
            },
        ]

        self.assertEqual(
            progression_reward_table_package_paths(settings),
            (PROGRESSION_MISSING, PROGRESSION_ROOT),
        )
        self.assertEqual(
            progression_reward_table_dependency_paths([root]),
            (PROGRESSION_NESTED,),
        )
        document = build_progression_perk_index(
            settings_asset=settings,
            reward_table_assets=[root, nested],
            candidate_records=candidate_records,
        )

        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["memberIds"], [PROGRESSION_PERK])
        self.assertEqual(document["coverage"]["unlockCategories"], 1)
        self.assertEqual(document["coverage"]["rootTableReferences"], 2)
        self.assertEqual(document["coverage"]["rootTablesResolved"], 1)
        self.assertEqual(document["coverage"]["rewardTablesTraversed"], 2)
        self.assertEqual(document["coverage"]["rewardRowsVisited"], 3)
        self.assertEqual(document["coverage"]["nestedRewardTableEdges"], 1)
        self.assertEqual(document["coverage"]["nonPerkDroppableReferences"], 1)
        self.assertEqual(document["coverage"]["uniquePerks"], 1)
        self.assertEqual(document["coverage"]["unresolvedReferences"], 1)
        self.assertEqual(document["unresolved"][0]["packagePath"], PROGRESSION_MISSING)

        source = document["entries"][0]["sources"][0]
        self.assertEqual(source["objective"], "Synthetic Objective")
        self.assertEqual(source["unlockCategory"], "Mission")
        self.assertEqual(len(source["steps"]), 2)
        self.assertEqual(source["steps"][0]["rewardType"], "RewardTable")
        self.assertEqual(source["steps"][1]["targetPackagePath"], PROGRESSION_PERK)
        self.assertEqual(source["steps"][1]["chance"], 1.0)
        self.assertNotIn(PROGRESSION_STALE, str(document))

        reversed_document = build_progression_perk_index(
            settings_asset=settings,
            reward_table_assets=[nested, root],
            candidate_records=list(reversed(candidate_records)),
        )
        self.assertEqual(document, reversed_document)

    def test_materializes_blueprint_parent_reward_table(self) -> None:
        settings = progression_settings([PROGRESSION_CHILD])
        child = inherited_progression_table()
        parent = progression_table(
            PROGRESSION_PARENT,
            [progression_reward_row("Droppable", PROGRESSION_PERK)],
        )
        candidate = {
            "id": PROGRESSION_PERK,
            "kind": "perk",
            "packagePath": PROGRESSION_PERK,
        }

        self.assertEqual(
            progression_reward_table_dependency_paths([child]),
            (PROGRESSION_PARENT,),
        )
        document = build_progression_perk_index(
            settings_asset=settings,
            reward_table_assets=[child, parent],
            candidate_records=[candidate],
        )

        self.assertEqual(document["status"], "complete")
        self.assertEqual(document["memberIds"], [PROGRESSION_PERK])
        self.assertEqual(document["coverage"]["blueprintParentTablesUsed"], 1)
        step = document["entries"][0]["sources"][0]["steps"][0]
        self.assertEqual(step["tablePackagePath"], PROGRESSION_CHILD)
        self.assertEqual(step["serializedByPackagePath"], PROGRESSION_PARENT)

    def test_authored_child_reward_table_does_not_require_its_parent(self) -> None:
        child = inherited_progression_table()
        child["exports"][1]["data"] = progression_table(
            PROGRESSION_CHILD,
            [progression_reward_row("Droppable", PROGRESSION_PERK)],
        )["exports"][0]["data"]

        self.assertEqual(progression_reward_table_dependency_paths([child]), ())

    def test_nested_cycle_fails_closed(self) -> None:
        settings = progression_settings([PROGRESSION_ROOT])
        cycle = progression_table(
            PROGRESSION_ROOT,
            [progression_reward_row("RewardTable", PROGRESSION_ROOT)],
        )
        document = build_progression_perk_index(
            settings_asset=settings,
            reward_table_assets=[cycle],
            candidate_records=[],
        )

        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["memberIds"], [])
        self.assertEqual(document["unresolved"][0]["reason"], "nested-reward-table-cycle")


class ProgressionExtractionTests(unittest.TestCase):
    def test_extracts_authored_roots_and_selected_nested_tables_dynamically(self) -> None:
        settings = progression_settings([PROGRESSION_ROOT, PROGRESSION_MISSING])
        root = imported_nested_progression_table()
        nested = progression_table(
            PROGRESSION_NESTED,
            [progression_reward_row("Droppable", PROGRESSION_PERK)],
        )
        assets = {
            PROGRESSION_SETTINGS: settings,
            PROGRESSION_ROOT: root,
            PROGRESSION_NESTED: nested,
        }
        members = {
            package: f"AFE2/Content/{package[6:]}.uasset"
            for package in assets
        }
        calls: list[str] = []

        def reader_result(*_args: object, **kwargs: object):
            label = kwargs["label"]
            calls.append(str(label))
            request = kwargs["request"]
            requested = [item["packagePath"] for item in request["assets"]]
            return (
                {
                    "assets": [assets[package] for package in requested],
                    "failures": [],
                    "icons": [],
                },
                Path("/unused"),
            )

        candidate = {
            "id": PROGRESSION_PERK,
            "kind": "perk",
            "packagePath": PROGRESSION_PERK,
        }
        with mock.patch.object(semantic_assets, "_extract_members"), mock.patch.object(
            semantic_assets,
            "_run_reader",
            side_effect=reader_result,
        ):
            document, failures = semantic_assets._extract_progression_perk_index(
                candidate_records=[candidate],
                members=members,
                paks_dir=Path("/game/Paks"),
                retoc=Path("/tools/retoc"),
                archive_key="not-a-real-key",
                reader=object(),  # type: ignore[arg-type]
                loose_root=Path("/work/loose"),
                work=Path("/work"),
                secret_environment_names=("AFE2_AES_KEY",),
            )

        self.assertEqual(
            calls,
            [
                "progression-settings",
                "progression-reward-tables-1",
                "progression-reward-tables-2",
            ],
        )
        self.assertEqual(document["memberIds"], [PROGRESSION_PERK])
        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(
            failures,
            [
                {
                    "packagePath": PROGRESSION_MISSING,
                    "reason": "progression-reward-table-had-no-uasset-member",
                    "stage": "progression-index",
                }
            ],
        )


class KitMembershipExtractionTests(unittest.TestCase):
    def test_discovers_live_registry_family_and_extracts_authorized_kits(self) -> None:
        registry = kit_registry()
        assets = {
            DEFAULT_STARTING: kit_reward_table(
                DEFAULT_STARTING,
                [character_unlock_row(CLASS_STARTING)],
            ),
            KIT_REGISTRY: registry,
            KIT_REWARD: kit_reward_table(
                KIT_REWARD,
                [character_unlock_row(CLASS_FUTURE)],
            ),
            KIT_NON_REWARD: asset(
                KIT_NON_REWARD,
                [prop("Objective", 2, "IntPropertyData")],
            ),
        }
        # This table authors its own RewardTable; its unrelated Blueprint
        # parent is not required admission evidence and must not be fetched.
        assets[KIT_REWARD]["imports"] = [
            {"objectName": KIT_REWARD_PARENT, "outerIndex": 0},
            {"objectName": "Unlock_Future_Class_Parent_C", "outerIndex": -1},
        ]
        assets[KIT_REWARD]["exports"].insert(
            0,
            {
                "objectName": "Unlock_Future_Class_C",
                "superIndex": -2,
                "type": "ClassExport",
                "data": [],
            },
        )
        members = {
            package: f"AFE2/Content/{package[6:]}.uasset" for package in assets
        }
        members.update(
            {
                "/Game/Metagame/DailyMetaMissions": (
                    "AFE2/Content/Metagame/DailyMetaMissions.uasset"
                ),
                "/Game/Metagame/Special/MM_Future_Class": (
                    "AFE2/Content/Metagame/Special/MM_Future_Class.uasset"
                ),
            }
        )
        package_index = {
            "packages": [
                {"packagePath": package}
                for package in [
                    *assets,
                    "/Game/Metagame/DailyMetaMissions",
                    "/Game/Metagame/Special/MM_Future_Class",
                ]
            ]
        }
        registry_package_paths = (
            semantic_assets._select_kit_reward_registry_packages(package_index)
        )
        self.assertEqual(
            set(registry_package_paths),
            {KIT_REGISTRY, "/Game/Metagame/DailyMetaMissions"},
        )
        # Keep one selected registry deliberately unbound. It must remain
        # visible as incomplete canonical evidence rather than disappearing.
        members.pop("/Game/Metagame/DailyMetaMissions")
        calls: list[str] = []

        def reader_result(*_args: object, **kwargs: object):
            label = str(kwargs["label"])
            calls.append(label)
            requested = [
                item["packagePath"] for item in kwargs["request"]["assets"]
            ]
            return (
                {
                    "assets": [assets[package] for package in requested],
                    "failures": [],
                    "icons": [],
                },
                Path("/unused"),
            )

        kits = [
            kit_record(KIT_STARTING, CLASS_STARTING),
            kit_record(KIT_FUTURE, CLASS_FUTURE),
            kit_record(KIT_LATENT, CLASS_LATENT),
        ]
        with mock.patch.object(semantic_assets, "_extract_members"), mock.patch.object(
            semantic_assets,
            "_run_reader",
            side_effect=reader_result,
        ):
            document, failures = semantic_assets._extract_kit_membership_index(
                kit_records=kits,
                members=members,
                registry_package_paths=registry_package_paths,
                paks_dir=Path("/game/Paks"),
                retoc=Path("/tools/retoc"),
                archive_key="not-a-real-key",
                reader=object(),  # type: ignore[arg-type]
                loose_root=Path("/work/loose"),
                work=Path("/work"),
                secret_environment_names=("AFE2_AES_KEY",),
            )

        self.assertEqual(
            calls,
            ["kit-membership-sources", "kit-membership-registry-imports"],
        )
        self.assertEqual(failures, [])
        self.assertEqual(document["memberIds"], [KIT_FUTURE, KIT_STARTING])
        self.assertNotIn(KIT_LATENT, document["memberIds"])
        self.assertEqual(document["status"], "incomplete")
        self.assertEqual(document["coverage"]["registryAssets"], 2)
        self.assertIn(
            {
                "packagePath": "/Game/Metagame/DailyMetaMissions",
                "reason": "metamission-registry-had-no-uasset-member",
                "sourceKind": "metamission-registry",
            },
            document["unresolved"],
        )


if __name__ == "__main__":
    unittest.main()
