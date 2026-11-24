from .db import SessionLocal
from .models import Vehicle

DATA = [
    (1, "2021 Toyota Corolla", "sedan", 18500, 5, ["economy", "carplay"], 32000, 35, True),
    (2, "2020 Honda CR-V", "suv", 23900, 5, ["cargo", "carplay"], 48000, 29, True),
    (3, "2022 Mazda3", "hatchback", 21900, 5, ["carplay", "sport"], 22000, 31, True),
    (4, "2019 Ford F-150", "truck", 28500, 5, ["towing", "cargo"], 65000, 20, True),
    (5, "2021 Kia Sorento", "suv", 25900, 7, ["cargo", "family"], 38000, 26, True),
    (6, "2018 Nissan Rogue", "suv", 17900, 5, ["cargo", "family"], 82000, 29, True),
    (7, "2017 Toyota RAV4", "suv", 19500, 5, ["cargo", "economy"], 42000, 26, True),
    (8, "2019 Hyundai Ioniq", "hatchback", 18900, 5, ["economy", "hybrid"], 68000, 55, True),
    (9, "2020 Toyota Camry", "sedan", 19900, 5, ["economy", "carplay"], 18000, 28, True),
    (10, "2019 Honda Insight", "sedan", 19900, 5, ["economy", "hybrid"], 76000, 52, True),
    (11, "2016 Dodge Grand Caravan", "suv", 15500, 7, ["family", "cargo"], 110000, 21, False),
    (12, "2018 Chevrolet Trax", "suv", 16500, 5, ["cargo"], None, None, True),
]


def seed():
    with SessionLocal() as db:
        for id, name, body, price, seats, features, mileage, mpg, available in DATA:
            existing = db.get(Vehicle, id)
            if not existing:
                db.add(
                    Vehicle(
                        id=id,
                        name=name,
                        body=body,
                        price=price,
                        seats=seats,
                        features=features,
                        mileage=mileage,
                        mpg=mpg,
                        available=available,
                    )
                )
            else:
                # Fill v0.1 attributes only. Never overwrite live prices or availability on reseed.
                if existing.mileage is None:
                    existing.mileage = mileage
                if existing.mpg is None:
                    existing.mpg = mpg
        db.flush()
        from .models import RentalRate

        for vid, daily, weekly, monthly in [
            (6, 4100, 22500, 87500),
            (7, 4400, 24000, 93500),
            (5, 5600, 29000, 104000),
            (9, 3500, 19000, 79000),
        ]:
            if not db.get(RentalRate, vid):
                db.add(
                    RentalRate(
                        vehicle_id=vid,
                        location="Tempe",
                        daily=daily,
                        weekly=weekly,
                        monthly=monthly,
                    )
                )
        db.commit()


if __name__ == "__main__":
    seed()
