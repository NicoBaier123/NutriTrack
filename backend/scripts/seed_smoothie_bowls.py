from __future__ import annotations

import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from sqlmodel import Session, select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "src"))

from app.core.database import engine  # noqa: E402
from app.models.foods import Food  # noqa: E402
from app.models.recipes import Recipe, RecipeItem  # noqa: E402
from app.utils.nutrition import macros_for_grams, sum_macros  # noqa: E402


@dataclass(frozen=True)
class FoodSeed:
    name: str
    kcal: float
    protein_g: float
    carbs_g: float
    fat_g: float


@dataclass(frozen=True)
class IngredientSeed:
    food_name: str
    grams: float


@dataclass(frozen=True)
class RecipeSeed:
    title: str
    tags: Sequence[str]
    ingredients: Sequence[IngredientSeed]
    instructions: Sequence[str]


FOODS: list[FoodSeed] = [
    # Fruits & tropical produce
    FoodSeed("Acai Puree", 70.0, 2.0, 6.0, 5.0),
    FoodSeed("Apple", 52.0, 0.3, 14.0, 0.2),
    FoodSeed("Apricot", 48.0, 1.4, 11.0, 0.4),
    FoodSeed("Banana", 89.0, 1.1, 22.8, 0.3),
    FoodSeed("Black Currant", 63.0, 1.4, 15.4, 0.4),
    FoodSeed("Blackberry", 43.0, 1.4, 9.6, 0.5),
    FoodSeed("Blueberry", 57.0, 0.7, 14.5, 0.3),
    FoodSeed("Cantaloupe", 34.0, 0.8, 8.2, 0.2),
    FoodSeed("Cherry", 63.0, 1.1, 16.0, 0.2),
    FoodSeed("Cranberry", 46.0, 0.4, 12.2, 0.1),
    FoodSeed("Dragon Fruit", 60.0, 1.2, 13.0, 0.0),
    FoodSeed("Fig", 74.0, 0.8, 19.0, 0.3),
    FoodSeed("Golden Berry", 53.0, 1.9, 11.2, 0.7),
    FoodSeed("Grape", 69.0, 0.7, 18.0, 0.2),
    FoodSeed("Grapefruit", 42.0, 0.8, 10.7, 0.2),
    FoodSeed("Guava", 68.0, 2.6, 14.0, 1.0),
    FoodSeed("Honeydew Melon", 36.0, 0.6, 9.1, 0.1),
    FoodSeed("Jackfruit", 95.0, 1.7, 23.0, 0.6),
    FoodSeed("Kiwi", 61.0, 1.1, 15.0, 0.5),
    FoodSeed("Lemon", 29.0, 1.1, 9.3, 0.3),
    FoodSeed("Lime", 30.0, 0.7, 11.0, 0.2),
    FoodSeed("Lychee", 66.0, 0.8, 16.5, 0.4),
    FoodSeed("Mango", 60.0, 0.8, 15.0, 0.4),
    FoodSeed("Nectarine", 44.0, 1.1, 10.5, 0.3),
    FoodSeed("Orange", 47.0, 0.9, 12.0, 0.1),
    FoodSeed("Papaya", 43.0, 0.5, 11.0, 0.3),
    FoodSeed("Passion Fruit", 97.0, 2.2, 23.0, 0.4),
    FoodSeed("Peach", 39.0, 0.9, 10.0, 0.3),
    FoodSeed("Pear", 57.0, 0.4, 15.0, 0.1),
    FoodSeed("Persimmon", 81.0, 0.6, 21.0, 0.3),
    FoodSeed("Pineapple", 50.0, 0.5, 13.0, 0.1),
    FoodSeed("Plum", 46.0, 0.7, 11.4, 0.3),
    FoodSeed("Pomegranate Arils", 83.0, 1.7, 19.0, 1.2),
    FoodSeed("Raspberry", 52.0, 1.2, 11.9, 0.7),
    FoodSeed("Red Currant", 56.0, 1.4, 13.8, 0.2),
    FoodSeed("Starfruit", 31.0, 1.0, 6.7, 0.3),
    FoodSeed("Strawberry", 32.0, 0.7, 7.7, 0.3),
    FoodSeed("Watermelon", 30.0, 0.6, 7.6, 0.2),

    # Leafy greens & herbs
    FoodSeed("Spinach", 23.0, 2.9, 3.6, 0.4),
    FoodSeed("Kale", 35.0, 4.3, 4.4, 1.0),
    FoodSeed("Swiss Chard", 19.0, 1.8, 3.7, 0.2),
    FoodSeed("Beet Greens", 22.0, 2.2, 4.3, 0.2),
    FoodSeed("Collard Greens", 32.0, 3.0, 6.0, 0.6),
    FoodSeed("Mint Leaves", 44.0, 3.3, 8.0, 0.7),
    FoodSeed("Basil Leaves", 23.0, 3.2, 3.9, 0.6),
    FoodSeed("Parsley", 36.0, 3.0, 6.3, 0.8),

    # Roots & vegetables
    FoodSeed("Ginger Root", 80.0, 1.8, 18.0, 0.8),
    FoodSeed("Turmeric Root", 312.0, 9.7, 67.0, 3.3),
    FoodSeed("Carrot", 41.0, 0.9, 10.0, 0.2),
    FoodSeed("Beetroot", 43.0, 1.6, 10.0, 0.2),
    FoodSeed("Sweet Potato", 86.0, 1.6, 20.1, 0.1),
    FoodSeed("Pumpkin (Sugar Pumpkin)", 26.0, 1.0, 6.5, 0.1),
    FoodSeed("Cucumber", 16.0, 0.7, 3.6, 0.1),

    # Coconut & plant-based liquids
    FoodSeed("Coconut Meat", 354.0, 3.3, 15.2, 33.5),
    FoodSeed("Coconut Water", 18.0, 0.7, 3.7, 0.2),
    FoodSeed("Coconut Flakes (Unsweetened)", 592.0, 5.0, 25.0, 65.0),
    FoodSeed("Coconut Chips", 660.0, 7.0, 24.0, 65.0),
    FoodSeed("Coconut Yogurt (Unsweetened)", 120.0, 1.5, 12.0, 7.0),
    FoodSeed("Homemade Almond Milk", 15.0, 0.6, 0.6, 1.2),
    FoodSeed("Homemade Cashew Milk", 25.0, 1.0, 2.0, 2.0),
    FoodSeed("Homemade Hemp Milk", 38.0, 2.0, 4.0, 2.5),

    # Nuts & nut butters
    FoodSeed("Almonds", 579.0, 21.0, 22.0, 50.0),
    FoodSeed("Walnuts", 654.0, 15.0, 14.0, 65.0),
    FoodSeed("Cashews", 553.0, 18.0, 30.0, 44.0),
    FoodSeed("Hazelnuts", 628.0, 15.0, 17.0, 61.0),
    FoodSeed("Macadamia Nuts", 718.0, 8.0, 14.0, 76.0),
    FoodSeed("Pistachios", 562.0, 20.0, 28.0, 45.0),
    FoodSeed("Brazil Nuts", 659.0, 14.0, 12.0, 67.0),
    FoodSeed("Tigernuts", 409.0, 4.0, 63.0, 24.0),
    FoodSeed("Almond Butter (Raw)", 614.0, 21.0, 19.0, 56.0),
    FoodSeed("Cashew Butter (Raw)", 553.0, 18.0, 30.0, 44.0),
    FoodSeed("Hazelnut Butter (Raw)", 628.0, 15.0, 17.0, 61.0),
    FoodSeed("Walnut Butter (Stone-Ground)", 654.0, 15.0, 14.0, 65.0),
    FoodSeed("Pumpkin Seed Butter", 615.0, 29.0, 13.0, 52.0),
    FoodSeed("Tahini (Stone-Ground)", 595.0, 17.0, 23.0, 53.0),

    # Seeds & pseudograins
    FoodSeed("Pumpkin Seeds", 559.0, 30.0, 11.0, 49.0),
    FoodSeed("Sunflower Seeds", 584.0, 21.0, 20.0, 51.0),
    FoodSeed("Flax Seeds", 534.0, 18.0, 29.0, 42.0),
    FoodSeed("Chia Seeds", 486.0, 17.0, 42.0, 31.0),
    FoodSeed("Hemp Seeds", 553.0, 32.0, 8.7, 49.0),
    FoodSeed("Sesame Seeds", 573.0, 18.0, 23.0, 50.0),
    FoodSeed("Poppy Seeds", 525.0, 18.0, 28.0, 42.0),
    FoodSeed("Sacha Inchi Seeds", 567.0, 33.0, 11.0, 49.0),
    FoodSeed("Rolled Oats", 389.0, 13.0, 67.0, 7.0),
    FoodSeed("Steel Cut Oats", 375.0, 12.0, 60.0, 7.0),
    FoodSeed("Sprouted Oat Groats", 330.0, 14.0, 60.0, 5.0),
    FoodSeed("Buckwheat Groats", 343.0, 13.0, 71.0, 3.0),
    FoodSeed("Sprouted Buckwheat", 332.0, 13.0, 70.0, 3.0),
    FoodSeed("Quinoa Flakes", 368.0, 14.0, 64.0, 6.0),

    # Superfoods & natural sweeteners
    FoodSeed("Acai Powder", 533.0, 9.0, 54.0, 33.0),
    FoodSeed("Raw Cacao Nibs", 604.0, 13.0, 33.0, 50.0),
    FoodSeed("Raw Cacao Powder", 228.0, 20.0, 58.0, 14.0),
    FoodSeed("Carob Powder", 222.0, 4.8, 88.9, 0.7),
    FoodSeed("Maca Powder", 325.0, 14.0, 71.0, 0.7),
    FoodSeed("Lucuma Powder", 345.0, 4.0, 88.0, 0.6),
    FoodSeed("Baobab Powder", 250.0, 2.0, 90.0, 0.5),
    FoodSeed("Camu Camu Powder", 339.0, 5.6, 85.0, 0.7),
    FoodSeed("Mesquite Powder", 367.0, 11.0, 81.0, 2.0),
    FoodSeed("Bee Pollen", 316.0, 24.0, 40.0, 5.0),
    FoodSeed("Date Paste", 282.0, 2.5, 75.0, 0.4),
]

assert len(FOODS) == 100, f"Expected 100 foods, found {len(FOODS)}"
FOOD_NAME_INDEX = {food.name.lower() for food in FOODS}
if len(FOOD_NAME_INDEX) != len(FOODS):
    raise RuntimeError("Food list contains duplicate names (case-insensitive).")


RECIPES: list[RecipeSeed] = [
    RecipeSeed(
        title="Sunrise Citrus Glow Bowl",
        tags=("smoothie_bowl", "citrus", "vegan"),
        ingredients=(
            IngredientSeed("Orange", 140.0),
            IngredientSeed("Mango", 90.0),
            IngredientSeed("Banana", 70.0),
            IngredientSeed("Homemade Almond Milk", 180.0),
            IngredientSeed("Chia Seeds", 15.0),
            IngredientSeed("Pomegranate Arils", 30.0),
            IngredientSeed("Bee Pollen", 10.0),
        ),
        instructions=(
            "Blend orange segments, mango, banana, and almond milk until silky.",
            "Pour into a chilled bowl.",
            "Finish with chia seeds, pomegranate arils, and bee pollen.",
        ),
    ),
    RecipeSeed(
        title="Forest Berry Crunch Bowl",
        tags=("smoothie_bowl", "berries", "vegetarian"),
        ingredients=(
            IngredientSeed("Blueberry", 100.0),
            IngredientSeed("Raspberry", 80.0),
            IngredientSeed("Strawberry", 70.0),
            IngredientSeed("Homemade Cashew Milk", 160.0),
            IngredientSeed("Buckwheat Groats", 30.0),
            IngredientSeed("Almonds", 15.0),
            IngredientSeed("Coconut Flakes (Unsweetened)", 10.0),
        ),
        instructions=(
            "Blend berries with cashew milk until smooth.",
            "Spoon into a bowl.",
            "Scatter buckwheat, chopped almonds, and coconut flakes on top.",
        ),
    ),
    RecipeSeed(
        title="Tropical Green Revive Bowl",
        tags=("smoothie_bowl", "greens", "vegan"),
        ingredients=(
            IngredientSeed("Spinach", 40.0),
            IngredientSeed("Pineapple", 120.0),
            IngredientSeed("Kiwi", 70.0),
            IngredientSeed("Mango", 60.0),
            IngredientSeed("Coconut Water", 150.0),
            IngredientSeed("Hemp Seeds", 18.0),
            IngredientSeed("Coconut Chips", 12.0),
        ),
        instructions=(
            "Blend spinach, pineapple, kiwi, mango, and coconut water until velvety.",
            "Transfer to a bowl.",
            "Top with hemp seeds and coconut chips for crunch.",
        ),
    ),
    RecipeSeed(
        title="Golden Immunity Bowl",
        tags=("smoothie_bowl", "immune", "vegan"),
        ingredients=(
            IngredientSeed("Orange", 120.0),
            IngredientSeed("Passion Fruit", 60.0),
            IngredientSeed("Ginger Root", 5.0),
            IngredientSeed("Turmeric Root", 3.0),
            IngredientSeed("Homemade Hemp Milk", 180.0),
            IngredientSeed("Maca Powder", 8.0),
            IngredientSeed("Almonds", 20.0),
        ),
        instructions=(
            "Blend orange, passion fruit pulp, ginger, turmeric, and hemp milk until smooth.",
            "Pour into a serving bowl.",
            "Sprinkle with maca powder and chopped almonds.",
        ),
    ),
    RecipeSeed(
        title="Jackfruit Paradise Bowl",
        tags=("smoothie_bowl", "tropical", "vegan"),
        ingredients=(
            IngredientSeed("Jackfruit", 130.0),
            IngredientSeed("Banana", 80.0),
            IngredientSeed("Coconut Yogurt (Unsweetened)", 120.0),
            IngredientSeed("Coconut Meat", 40.0),
            IngredientSeed("Almond Butter (Raw)", 20.0),
            IngredientSeed("Coconut Chips", 10.0),
            IngredientSeed("Date Paste", 15.0),
        ),
        instructions=(
            "Blend jackfruit, banana, and coconut yogurt until creamy.",
            "Fold in coconut meat and almond butter.",
            "Serve topped with coconut chips and ribbons of date paste.",
        ),
    ),
    RecipeSeed(
        title="Cacao Almond Dream Bowl",
        tags=("smoothie_bowl", "cacao", "vegetarian"),
        ingredients=(
            IngredientSeed("Acai Puree", 140.0),
            IngredientSeed("Banana", 70.0),
            IngredientSeed("Homemade Almond Milk", 170.0),
            IngredientSeed("Raw Cacao Powder", 12.0),
            IngredientSeed("Almond Butter (Raw)", 25.0),
            IngredientSeed("Raw Cacao Nibs", 15.0),
            IngredientSeed("Pumpkin Seeds", 15.0),
        ),
        instructions=(
            "Blend acai, banana, almond milk, cacao powder, and almond butter until thick.",
            "Scoop into a bowl.",
            "Top with cacao nibs and pumpkin seeds.",
        ),
    ),
    RecipeSeed(
        title="Garden Greens Detox Bowl",
        tags=("smoothie_bowl", "detox", "vegan"),
        ingredients=(
            IngredientSeed("Collard Greens", 40.0),
            IngredientSeed("Cucumber", 100.0),
            IngredientSeed("Pear", 90.0),
            IngredientSeed("Lime", 20.0),
            IngredientSeed("Homemade Cashew Milk", 160.0),
            IngredientSeed("Parsley", 10.0),
            IngredientSeed("Sacha Inchi Seeds", 18.0),
        ),
        instructions=(
            "Blend collard greens, cucumber, pear, lime juice, and cashew milk until smooth.",
            "Pour into a bowl.",
            "Finish with chopped parsley and sacha inchi seeds.",
        ),
    ),
    RecipeSeed(
        title="Persimmon Spice Bowl",
        tags=("smoothie_bowl", "seasonal", "vegetarian"),
        ingredients=(
            IngredientSeed("Persimmon", 140.0),
            IngredientSeed("Sweet Potato", 60.0),
            IngredientSeed("Pear", 60.0),
            IngredientSeed("Homemade Almond Milk", 150.0),
            IngredientSeed("Lucuma Powder", 8.0),
            IngredientSeed("Walnut Butter (Stone-Ground)", 18.0),
            IngredientSeed("Chia Seeds", 15.0),
            IngredientSeed("Bee Pollen", 8.0),
        ),
        instructions=(
            "Blend persimmon, sweet potato, pear, almond milk, and lucuma until creamy.",
            "Transfer to a bowl and swirl in walnut butter.",
            "Top with chia seeds and bee pollen.",
        ),
    ),
    RecipeSeed(
        title="Radiant Roots Bowl",
        tags=("smoothie_bowl", "beet", "vegan"),
        ingredients=(
            IngredientSeed("Beetroot", 100.0),
            IngredientSeed("Raspberry", 80.0),
            IngredientSeed("Strawberry", 70.0),
            IngredientSeed("Coconut Water", 160.0),
            IngredientSeed("Flax Seeds", 18.0),
            IngredientSeed("Hazelnut Butter (Raw)", 20.0),
            IngredientSeed("Golden Berry", 30.0),
        ),
        instructions=(
            "Blend beetroot, raspberries, strawberries, and coconut water until silky.",
            "Spoon into a bowl.",
            "Scatter flax seeds, drizzle hazelnut butter, and add golden berries.",
        ),
    ),
    RecipeSeed(
        title="Tropical Sunset Pitaya Bowl",
        tags=("smoothie_bowl", "tropical", "vegan"),
        ingredients=(
            IngredientSeed("Dragon Fruit", 150.0),
            IngredientSeed("Pineapple", 100.0),
            IngredientSeed("Mango", 80.0),
            IngredientSeed("Coconut Water", 150.0),
            IngredientSeed("Coconut Yogurt (Unsweetened)", 100.0),
            IngredientSeed("Pistachios", 20.0),
            IngredientSeed("Coconut Flakes (Unsweetened)", 12.0),
        ),
        instructions=(
            "Blend dragon fruit, pineapple, mango, coconut water, and coconut yogurt until thick.",
            "Pour into a chilled bowl.",
            "Finish with pistachios and coconut flakes.",
        ),
    ),
    RecipeSeed(
        title="Autumn Harvest Bowl",
        tags=("smoothie_bowl", "autumn", "vegetarian"),
        ingredients=(
            IngredientSeed("Pumpkin (Sugar Pumpkin)", 120.0),
            IngredientSeed("Apple", 100.0),
            IngredientSeed("Carrot", 70.0),
            IngredientSeed("Homemade Cashew Milk", 160.0),
            IngredientSeed("Date Paste", 20.0),
            IngredientSeed("Pumpkin Seed Butter", 22.0),
            IngredientSeed("Pumpkin Seeds", 18.0),
            IngredientSeed("Pomegranate Arils", 30.0),
        ),
        instructions=(
            "Blend pumpkin, apple, carrot, cashew milk, and date paste until smooth.",
            "Spoon into a bowl.",
            "Crown with pumpkin seed butter, pumpkin seeds, and pomegranate arils.",
        ),
    ),
    RecipeSeed(
        title="Minted Melon Silk Bowl",
        tags=("smoothie_bowl", "melon", "vegan"),
        ingredients=(
            IngredientSeed("Honeydew Melon", 140.0),
            IngredientSeed("Cantaloupe", 100.0),
            IngredientSeed("Cucumber", 60.0),
            IngredientSeed("Mint Leaves", 10.0),
            IngredientSeed("Coconut Yogurt (Unsweetened)", 100.0),
            IngredientSeed("Hemp Seeds", 15.0),
            IngredientSeed("Coconut Chips", 10.0),
        ),
        instructions=(
            "Blend honeydew, cantaloupe, cucumber, mint, and coconut yogurt until silky.",
            "Pour into a bowl.",
            "Top with hemp seeds and coconut chips.",
        ),
    ),
    RecipeSeed(
        title="Peach Basil Bliss Bowl",
        tags=("smoothie_bowl", "stonefruit", "vegetarian"),
        ingredients=(
            IngredientSeed("Peach", 120.0),
            IngredientSeed("Nectarine", 80.0),
            IngredientSeed("Banana", 60.0),
            IngredientSeed("Basil Leaves", 8.0),
            IngredientSeed("Homemade Hemp Milk", 160.0),
            IngredientSeed("Lucuma Powder", 8.0),
            IngredientSeed("Macadamia Nuts", 20.0),
            IngredientSeed("Coconut Flakes (Unsweetened)", 12.0),
        ),
        instructions=(
            "Blend peaches, nectarines, banana, basil, and hemp milk until creamy.",
            "Pour into a bowl.",
            "Dust with lucuma, crushed macadamias, and coconut flakes.",
        ),
    ),
    RecipeSeed(
        title="Citrus Camu Vitality Bowl",
        tags=("smoothie_bowl", "citrus", "vegetarian"),
        ingredients=(
            IngredientSeed("Grapefruit", 120.0),
            IngredientSeed("Lemon", 40.0),
            IngredientSeed("Mango", 90.0),
            IngredientSeed("Camu Camu Powder", 6.0),
            IngredientSeed("Coconut Yogurt (Unsweetened)", 110.0),
            IngredientSeed("Hemp Seeds", 16.0),
            IngredientSeed("Pumpkin Seeds", 14.0),
            IngredientSeed("Date Paste", 12.0),
        ),
        instructions=(
            "Blend grapefruit segments, lemon, mango, camu camu powder, and coconut yogurt until smooth.",
            "Spoon into a bowl.",
            "Top with hemp seeds, pumpkin seeds, and a drizzle of date paste.",
        ),
    ),
    RecipeSeed(
        title="Guava Pine Oat Bowl",
        tags=("smoothie_bowl", "fiber", "vegan"),
        ingredients=(
            IngredientSeed("Guava", 120.0),
            IngredientSeed("Pineapple", 100.0),
            IngredientSeed("Banana", 70.0),
            IngredientSeed("Rolled Oats", 35.0),
            IngredientSeed("Homemade Almond Milk", 170.0),
            IngredientSeed("Sunflower Seeds", 18.0),
            IngredientSeed("Bee Pollen", 8.0),
        ),
        instructions=(
            "Blend guava, pineapple, banana, oats, and almond milk until thick.",
            "Scoop into a bowl.",
            "Finish with sunflower seeds and bee pollen.",
        ),
    ),
    RecipeSeed(
        title="Acai Boost Bowl",
        tags=("smoothie_bowl", "acai", "vegan"),
        ingredients=(
            IngredientSeed("Acai Puree", 140.0),
            IngredientSeed("Acai Powder", 6.0),
            IngredientSeed("Blueberry", 90.0),
            IngredientSeed("Banana", 70.0),
            IngredientSeed("Homemade Cashew Milk", 170.0),
            IngredientSeed("Chia Seeds", 18.0),
            IngredientSeed("Raw Cacao Nibs", 15.0),
            IngredientSeed("Almonds", 15.0),
        ),
        instructions=(
            "Blend acai puree, acai powder, blueberries, banana, and cashew milk until thick.",
            "Pour into a bowl.",
            "Top with chia seeds, cacao nibs, and sliced almonds.",
        ),
    ),
    RecipeSeed(
        title="Golden Berry Glow Bowl",
        tags=("smoothie_bowl", "vitamin_c", "vegan"),
        ingredients=(
            IngredientSeed("Golden Berry", 100.0),
            IngredientSeed("Orange", 90.0),
            IngredientSeed("Pineapple", 80.0),
            IngredientSeed("Baobab Powder", 7.0),
            IngredientSeed("Coconut Water", 160.0),
            IngredientSeed("Sesame Seeds", 12.0),
            IngredientSeed("Coconut Chips", 10.0),
            IngredientSeed("Hazelnuts", 18.0),
        ),
        instructions=(
            "Blend golden berries, orange, pineapple, baobab powder, and coconut water until bright.",
            "Pour into a bowl.",
            "Garnish with sesame seeds, coconut chips, and chopped hazelnuts.",
        ),
    ),
    RecipeSeed(
        title="Lychee Lime Breeze Bowl",
        tags=("smoothie_bowl", "refreshing", "vegan"),
        ingredients=(
            IngredientSeed("Lychee", 120.0),
            IngredientSeed("Lime", 25.0),
            IngredientSeed("Mango", 90.0),
            IngredientSeed("Homemade Hemp Milk", 160.0),
            IngredientSeed("Quinoa Flakes", 35.0),
            IngredientSeed("Pistachios", 18.0),
            IngredientSeed("Sacha Inchi Seeds", 15.0),
            IngredientSeed("Coconut Flakes (Unsweetened)", 10.0),
        ),
        instructions=(
            "Blend lychee, lime juice, mango, hemp milk, and quinoa flakes until smooth.",
            "Pour into a bowl.",
            "Top with pistachios, sacha inchi seeds, and coconut flakes.",
        ),
    ),
    RecipeSeed(
        title="Mango Lucuma Crunch Bowl",
        tags=("smoothie_bowl", "energy", "vegan"),
        ingredients=(
            IngredientSeed("Mango", 120.0),
            IngredientSeed("Persimmon", 80.0),
            IngredientSeed("Banana", 70.0),
            IngredientSeed("Lucuma Powder", 8.0),
            IngredientSeed("Homemade Almond Milk", 170.0),
            IngredientSeed("Tigernuts", 25.0),
            IngredientSeed("Pumpkin Seeds", 15.0),
            IngredientSeed("Coconut Chips", 12.0),
        ),
        instructions=(
            "Blend mango, persimmon, banana, lucuma powder, and almond milk until velvety.",
            "Scoop into a bowl.",
            "Sprinkle with chopped tigernuts, pumpkin seeds, and coconut chips.",
        ),
    ),
    RecipeSeed(
        title="Sacha Super Seed Bowl",
        tags=("smoothie_bowl", "protein", "vegan"),
        ingredients=(
            IngredientSeed("Papaya", 130.0),
            IngredientSeed("Kiwi", 80.0),
            IngredientSeed("Raspberry", 60.0),
            IngredientSeed("Homemade Cashew Milk", 170.0),
            IngredientSeed("Sacha Inchi Seeds", 18.0),
            IngredientSeed("Flax Seeds", 16.0),
            IngredientSeed("Chia Seeds", 15.0),
            IngredientSeed("Hemp Seeds", 15.0),
            IngredientSeed("Date Paste", 12.0),
        ),
        instructions=(
            "Blend papaya, kiwi, raspberries, cashew milk, and date paste until creamy.",
            "Pour into a bowl.",
            "Top with sacha inchi, flax, chia, and hemp seeds.",
        ),
    ),
]
assert len(RECIPES) == 20, f"Expected 20 recipes, found {len(RECIPES)}"
REQUIRED_FOODS = {ingredient.food_name for recipe in RECIPES for ingredient in recipe.ingredients}
MISSING_SEED_FOODS = sorted(name for name in REQUIRED_FOODS if name.lower() not in FOOD_NAME_INDEX)
if MISSING_SEED_FOODS:
    raise RuntimeError(f"Recipes reference unknown foods: {', '.join(MISSING_SEED_FOODS)}")


def load_foods(session: Session) -> int:
    existing = {name.lower() for (name,) in session.exec(select(Food.name))}
    new_foods = [
        Food(
            name=seed.name,
            kcal=seed.kcal,
            protein_g=seed.protein_g,
            carbs_g=seed.carbs_g,
            fat_g=seed.fat_g,
        )
        for seed in FOODS
        if seed.name.lower() not in existing
    ]
    if new_foods:
        session.add_all(new_foods)
        session.commit()
    return len(new_foods)


def load_recipes(session: Session) -> int:
    foods = {food.name.lower(): food for food in session.exec(select(Food))}
    inserted = 0
    for recipe_seed in RECIPES:
        if session.exec(select(Recipe).where(Recipe.title == recipe_seed.title)).first():
            continue
        macros_list = []
        for ingredient in recipe_seed.ingredients:
            food = foods.get(ingredient.food_name.lower())
            if not food:
                raise ValueError(f"Food '{ingredient.food_name}' not found in database")
            macros_list.append(
                macros_for_grams(
                    float(food.kcal),
                    float(food.protein_g),
                    float(food.carbs_g),
                    float(food.fat_g),
                    ingredient.grams,
                )
            )
        totals = sum_macros(macros_list)
        recipe = Recipe(
            title=recipe_seed.title,
            source="library",
            request_message="smoothie bowl seed",
            request_day=None,
            request_servings=1,
            preferences_json=None,
            constraints_json=None,
            instructions_json=list(recipe_seed.instructions),
            time_minutes=10,
            difficulty="easy",
            tags=",".join(recipe_seed.tags),
            macros_kcal=round(totals.kcal, 1),
            macros_protein_g=round(totals.protein_g, 1),
            macros_carbs_g=round(totals.carbs_g, 1),
            macros_fat_g=round(totals.fat_g, 1),
        )
        session.add(recipe)
        session.flush()
        for ingredient in recipe_seed.ingredients:
            session.add(
                RecipeItem(
                    recipe_id=recipe.id,
                    name=ingredient.food_name,
                    grams=ingredient.grams,
                )
            )
        inserted += 1
    session.commit()
    return inserted


def main() -> None:
    with Session(engine) as session:
        foods_inserted = load_foods(session)
        recipes_inserted = load_recipes(session)
    print(f"Inserted {foods_inserted} foods and {recipes_inserted} recipes.")


if __name__ == "__main__":
    main()
