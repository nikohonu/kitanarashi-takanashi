import csv
import datetime as dt
import math
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Generator

import msgspec

import kitanarashi_takanashi.anki as anki

total_time = 0
index = 1


class InputData(msgspec.Struct):
    hours: int
    anime_episodes: int
    characters_to_read: int
    main_task1_name: str
    main_task2_name: str


@dataclass
class Task:
    name: str
    duration: int

    def print(self):
        global total_time
        global index
        print(f"{index}. {self.name} ({self.duration}m)")
        total_time += self.duration
        index += 1


@dataclass
class Deck:
    name: str
    reviews: int


def get_input_data() -> InputData:
    input_data_path = Path().home() / "kt.toml"
    if input_data_path.is_file():
        input_data_bytes = input_data_path.read_bytes()
        return msgspec.toml.decode(input_data_bytes, type=InputData)
    else:
        print(
            "kt.toml don't exist in current directory, but I will create "
            "empty one for you. Restatr afer modifing it."
        )
        input_data_bytes = msgspec.toml.encode(InputData(8, 3, 1000, "work1", "work2"))
        input_data_path.write_bytes(input_data_bytes)
        sys.exit()


def get_routine_tasks() -> Generator[Task]:
    routine_tasks_path = Path().home() / "local-git/notes"
    for file_path in routine_tasks_path.glob("**/*.md"):
        with file_path.open() as file:
            for line in file.readlines():
                line = line[:-1]
                schedule_position = line.find("schedule:")
                if not (line.startswith("- [ ]") and schedule_position != -1):
                    continue
                schedule = dt.date.fromisoformat(
                    line[schedule_position + 9 : schedule_position + 9 + 10]
                )
                if schedule > dt.date.today():
                    continue
                duration_position = line.find("duration:")
                if duration_position == -1:
                    print(
                        f'task "{line}" from "{file_path}" dosen\'t have '
                        "duration! Set a duration in minutes, for example "
                        '"duration:5".'
                    )
                    sys.exit()
                end_of_name = line[: line.find(":")].rfind(" ")
                duration_end_position = (
                    line[duration_position:].find(" ") + duration_position
                )
                duration = int(line[duration_position + 9 : duration_end_position])
                name = line[6:end_of_name]
                yield Task(name, duration)


def get_anime_tasks(anime_episodes: int):
    return [Task(f"anime - {i+1}", 21) for i in range(anime_episodes)]


def get_anki_tasks(hours: int):
    deck_names = anki.invoke("deckNames")
    deck_stats = anki.invoke("getDeckStats", decks=deck_names)
    decks: list[Deck] = []

    one_week_ago = dt.datetime.now() - dt.timedelta(days=7)
    start_timestamp = round(one_week_ago.timestamp() * 1000)
    estimated_duration = 0

    for deck_data in deck_stats.values():
        reviews = anki.invoke(
            "cardReviews", deck=deck_data["name"], startID=start_timestamp
        )
        estimated_duration += sum(review[-2] for review in reviews) / 1000 / 60 / 7
        review_count = deck_data["review_count"]
        if review_count > 0:
            decks.append(Deck(deck_data["name"], review_count))

    decks = list(sorted(decks, key=lambda deck: deck.reviews))

    total_session_count = 8
    duration_per_session = round(estimated_duration / total_session_count)

    for i in range(total_session_count):
        name = ""
        session_count = total_session_count - i
        total_review_count = sum(deck.reviews for deck in decks)
        count_per_session = round(total_review_count / session_count)
        need_reviews = count_per_session
        total_review_count -= need_reviews

        while need_reviews != 0:
            deck = decks[0]
            start_reviews = deck.reviews
            if deck.reviews > need_reviews:
                deck.reviews -= need_reviews
                need_reviews = 0
            else:
                need_reviews -= deck.reviews
                deck.reviews = 0
                decks.pop(0)

            if name == "":
                name = f"{deck.name} {start_reviews} - {deck.reviews}"
            else:
                name += f", {deck.name} {start_reviews} - {deck.reviews}"

        yield Task(name.lower(), duration_per_session)


def get_reading_tasks(sessions, need_chars):
    # calc stats
    ln_path = Path().home() / "local-git/japanese/ln.csv"
    vn_path = Path().home() / "local-git/japanese/vn.csv"
    chars = 0
    minutes = 0
    for path in [ln_path, vn_path]:
        with path.open() as csvfile:
            spamreader = csv.reader(csvfile, delimiter=",", quotechar="|")
            skip = True
            for row in spamreader:
                if skip:
                    skip = False
                    continue
                chars += int(row[-2])
                minutes += int(row[-1])
    speed = minutes / chars

    # generate task, using stats data to calc duration
    chars_per_session = math.ceil(need_chars / sessions)
    return [
        Task(
            f"read {chars_per_session} chars",
            round(chars_per_session * speed),
        )
        for _ in range(sessions)
    ]


def main():
    # gather data
    input_data = get_input_data()
    routine_tasks = list(get_routine_tasks())
    anki_tasks = list(get_anki_tasks(input_data.hours))
    session_count = len(anki_tasks)
    anime_tasks = get_anime_tasks(input_data.anime_episodes)
    session_per_anime = math.floor(session_count / input_data.anime_episodes)
    reading_tasks = get_reading_tasks(session_count, input_data.characters_to_read)

    # calc remain duration for all task except main tasks and routine
    remaining_time_without_routine = input_data.hours * 60 - sum(
        [task.duration for task in anime_tasks + anki_tasks + reading_tasks]
    )

    # calc reading duration for routine, main task 1 and main task 2
    remaining_for_routine = sum([task.duration for task in routine_tasks])
    remaining_for_task1 = math.floor(
        (remaining_time_without_routine - remaining_for_routine) / 2
    )
    remaining_for_task2 = remaining_for_task1

    # print result
    for i in range(session_count):
        print(f"{'-'*10}Session {i + 1}{'-'*10}")
        anki_tasks.pop(0).print()
        have_time = remaining_for_routine + remaining_for_task1 + remaining_for_task2
        duration_per_session = math.floor(have_time / (session_count - i))
        while duration_per_session > 0:
            if remaining_for_routine > 0:
                task = routine_tasks.pop(0)
                duration_per_session -= task.duration
                remaining_for_routine -= task.duration
                task.print()
            elif remaining_for_task1 > 0:
                task = Task(
                    input_data.main_task1_name,
                    duration_per_session
                    if remaining_for_task1 > duration_per_session
                    else remaining_for_task1,
                )
                remaining_for_task1 -= task.duration
                duration_per_session -= task.duration
                task.print()
            elif remaining_for_task2 > 0:
                task = Task(
                    input_data.main_task2_name,
                    duration_per_session
                    if remaining_for_task2 > duration_per_session
                    else remaining_for_task2,
                )
                remaining_for_task2 -= task.duration
                duration_per_session -= task.duration
                task.print()
        reading_tasks.pop(0).print()
        if i % session_per_anime == 0 and anime_tasks:
            anime_tasks.pop(0).print()
    print("-" * 32)
    print("Total duration:", total_time / 60)


if __name__ == "__main__":
    main()
