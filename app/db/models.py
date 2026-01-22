from datetime import datetime

from django.db import models


class CardSet(models.TextChoices):
    GENETIC_APEX = "A1", "Genetic Apex"
    MYTHICAL_ISLAND = "A1a", "Mythical Island"
    SPACE_TIME_SMACKDOWN = "A2", "Space-Time Smackdown"
    TRIUMPHANT_LIGHT = "A2a", "Triumphant Light"
    SHINING_REVELRY = "A2b", "Shining Revelry"
    CELESTIAL_GUARDIANS = "A3", "Celestial Guardians"
    EXTRADIMENSIONAL_CRISIS = "A3a", "Extradimensional Crisis"
    EEVEE_GROVE = "A3b", "Eevee Grove"
    WISDOM_OF_SEA_AND_SKY = "A4", "Wisdom of Sea and Sky"
    SECLUDED_SPRINGS = "A4a", "Secluded Springs"
    DELUXE_PACK_EX = "A4b", "Deluxe Pack Ex"
    MEGA_RISING = "B1", "Mega Rising"
    CRIMSON_BLAZE = "B1a", "Crimson Blaze"
    FANTASTICAL_PARADE = "B2", "Fantastical Parade"
    PROMO_A = "P-A", "Promo A"
    PROMO_B = "P-B", "Promo B"

    @staticmethod
    def name_map():
        return dict(reversed(list(dict(zip(CardSet.values, CardSet.labels)).items())))


def translate_set_name(set_name):
    ptcgpb_names = {
        # Genetic Apex
        "Charizard": "A1",
        "Mewtwo": "A1",
        "Pikachu": "A1",
        # Mythical Island
        "Mew": "A1a",
        # Space-Time Smackdown
        "Palkia": "A2",
        "Dialga": "A2",
        # Triumphant Light
        "Arceus": "A2a",
        # Shining Revelry
        "Shining": "A2b",
        # Celestial Guardians
        "Lunala": "A3",
        "Solgaleo": "A3",
        # Extradimensional Crisis
        "Buzzwole": "A3a",
        # Eevee Grove
        "Eevee": "A3b",
        # Wisdom of Sea and Sky
        "HoOh": "A4",
        "Lugia": "A4",
        # Secluded Springs
        "Springs": "A4a",
        # Deluxe Pack: ex
        "Deluxe": "A4b",
        "Deluxe Pack Ex": "A4b",
        # Mega Rising
        "Mega Rising": "B1",  # Why do we have an extra value for the general pack?
        "MegaBlaziken": "B1",
        "MegaGyarados": "B1",
        "MegaAltaria": "B1",
        # Crimson Blaze
        "CrimsonBlaze": "B1a",
        # Fantastical Parade
        "Parade": "B2",
    }
    return ptcgpb_names.get(set_name, None)


class Screenshot(models.Model):
    timestamp = models.CharField(max_length=255, null=True, blank=True)
    account = models.ForeignKey(
        "Account", on_delete=models.CASCADE, null=True, blank=True
    )
    set = models.CharField(
        max_length=100, choices=CardSet.choices, null=True, blank=True
    )
    name = models.TextField(unique=True, null=True, blank=True)
    processed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def cards(self):
        return self.screenshotcard_set.all()

    class Meta:
        db_table = "screenshots"
        indexes = [
            models.Index(fields=["name"], name="idx_screenshots_clean_file"),
            models.Index(fields=["account"], name="idx_screenshots_account"),
            models.Index(fields=["timestamp"], name="idx_screenshots_timestamp"),
            models.Index(fields=["processed"], name="idx_screenshots_processed"),
        ]

    def __str__(self):
        return f"Screenshot {self.pk} - {self.name}"


class Card(models.Model):
    class Rarity(models.TextChoices):
        COMMON = "1D", "Common"
        UNCOMMON = "2D", "Uncommon"
        RARE = "3D", "Rare"
        DOUBLE_RARE = "4D", "Double Rare"
        ILLUSTRATION_RARE = "1S", "Illustration Rare"
        SUPER_SPECIAL_RARE = "2S", "Super / Special Rare"
        IMMERSIVE = "3S", "Immersive"
        CROWN_RARE = "CR", "Crown Rare"

        @staticmethod
        def rarity_map():
            return dict(zip(Card.Rarity.values, Card.Rarity.labels))

    name = models.CharField(max_length=255, null=True, blank=True)
    set = models.CharField(
        max_length=100, choices=CardSet.choices, null=True, blank=True
    )
    code = models.CharField(max_length=100, null=True, blank=True)
    image_path = models.TextField(null=True, blank=True)
    rarity = models.CharField(
        max_length=100, choices=Rarity.choices, null=True, blank=True
    )
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "cards"
        unique_together = (("code", "set"),)
        indexes = [
            models.Index(fields=["name"], name="idx_cards_name"),
        ]

    def save(self, *args, **kwargs):
        if self.name and "(" in self.name:
            # Extract rarity if not already set or is default
            import re

            match = re.search(r"\(([^)]+)\)", self.name)
            if match:
                new_rarity = match.group(1)
                if not self.rarity or self.rarity == "1D":
                    self.rarity = new_rarity
            self.name = self.name.split("(")[0].strip()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"Card {self.pk} - {self.name} ({self.set})"


class ScreenshotCard(models.Model):
    screenshot = models.ForeignKey(
        Screenshot, on_delete=models.CASCADE, db_column="screenshot_id"
    )
    card = models.ForeignKey(Card, on_delete=models.CASCADE, db_column="card_id")
    position = models.IntegerField()
    confidence = models.FloatField()
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = "screenshot_cards"
        unique_together = (("screenshot", "card", "position"),)
        indexes = [
            models.Index(fields=["screenshot"], name="idx_screenshot_cards_screen_id"),
            models.Index(fields=["card"], name="idx_screenshot_cards_card_id"),
        ]

    def __str__(self):
        return f"ScreenshotCard {self.pk} (Screenshot: {self.screenshot}, Card: {self.card})"


class Account(models.Model):
    name = models.CharField(max_length=255, unique=True, null=True, blank=True)
    shinedust = models.CharField(max_length=100, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

    @property
    def age(self):
        if not self.name:
            return 0
        try:
            dt = datetime.strptime(str(self.name), "%Y%m%d%H%M%S")
            return (datetime.now() - dt).days
        except (ValueError, TypeError):
            return 0

    class Meta:
        db_table = "accounts"

    def __str__(self):
        return f"Account {self.pk} - {self.name}"
