import pandas as pd
import json
import os
import mysql.connector
from sqlalchemy import create_engine, text, exc
from concurrent.futures import ThreadPoolExecutor
import logging

# Configure logging
log_file = "insertion_log1.txt"  # Specify your log file
logging.basicConfig(filename=log_file, level=logging.INFO,  # Set logging level
                    format='%(asctime)s - %(levelname)s - %(message)s')

# Create MySQL connection pool for efficiency
def get_db_engine():
    return create_engine("mysql+mysqlconnector://root:root@localhost/cricket_dataset_practice", pool_size=10, max_overflow=5)

def insert_dict_into_database(data, table_name, engine):
    """Inserts a dictionary into the database."""
    try:
        with engine.connect() as conn:  # Use context manager
            ins = text(f"INSERT INTO {table_name} ({', '.join(data.keys())}) VALUES ({', '.join([':'+k for k in data.keys()])})")
            conn.execute(ins, data)
            logging.info(f"Inserted into {table_name}: {data}") # log the data that has been inserted.
            #print(f"✅ Inserted into {table_name}")
    except exc.IntegrityError as e:  # Handle unique key error
        logging.error(f"Integrity Error inserting into {table_name}: {e} Data: {data}") # log the data that has been inserted.
        #print(f"❌ Integrity Error inserting into {table_name}: {e}")
        return False  # Indicate failure
    except Exception as e:
        logging.error(f"Error inserting into {table_name}: {e} Data: {data}") # log the data that has been inserted.
        #print(f"❌ Error inserting into {table_name}: {e}")
        return False  # Indicate failure
    return True  # Indicate success

def check_record_exists(conn, table, column, value):
    """Checks if a record exists in a table."""
    try:
        query = text(f"SELECT 1 FROM {table} WHERE {column} = :value")
        result = conn.execute(query, {"value": value}).scalar()
        return result is not None  # Returns True if record exists, False otherwise
    except Exception as e:
        logging.error(f"Error checking record in {table}: {e}")
        return False  # Return False in case of an error

def process_json_file(filepath):
    """Process a single JSON file and insert into MySQL (direct dict inserts)."""
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            data = json.load(f)
            matchID = os.path.basename(filepath).split('.')[0]
            print("current file: - ",matchID)

            d = data.get('info', {})
            registry = d.get('registry', {}).get('people', {})

            engine = get_db_engine()  # Get engine *inside* the function

            # ✅ Insert `registry` (Direct Dict Inserts)
            for person_name, person_id in registry.items():
                registry_data = {"person_id": person_id, "person_name": person_name}
                if not insert_dict_into_database(registry_data, "registry", engine): # check the return value. if insert fails, then continue to the next person.
                    continue
            print("crossed regitry",matchID)       
            # ✅ Insert `match_details` (Direct Dict Insert)
            match = {
                "match_id": matchID,
                "city": d.get('city', None),
                "gender": d.get('gender', None), 
                "match_type": d.get('match_type', None), 
                "match_type_number": d.get('match_type_number', None), 
                "overs": d.get('overs', None), 
                "season": d.get('season', None), 
                "team_type": d.get('team_type', None), 
                "venue": d.get('venue', None),
                "team1": d.get("teams", [None, None])[0],
                "team2": d.get("teams", [None, None])[1],
                "toss_winner": d.get("toss", {}).get("winner", None),
                "toss_decision": d.get("toss", {}).get("decision", None),
                "winner": d.get("outcome", {}).get("winner", None), 
                "outcome_type": json.dumps(d.get("outcome", {}).get("by", {})) if isinstance(d.get("outcome", {}).get("by"), dict) else d.get("outcome", {}).get("by"),
                "player_of_match": ", ".join([registry.get(i, "Unknown") for i in d.get("player_of_match", [])]),
                "balls_per_over": d.get("balls_per_over", None)
            }
            print("Going to insert match_deatils of",matchID)
            insert_dict_into_database(match, "match_details", engine)


            # ✅ Insert `officials` (Direct Dict Inserts)
            for off in d.get('officials', {}):
                for person in d['officials'][off]:
                    official_data = {"match_id": matchID, "person_id": registry.get(person, None), "official_type": off}
                    insert_dict_into_database(official_data, "officials", engine)
            print("crossed officials",matchID)

            # ✅ Insert `players` (Direct Dict Inserts)
            for team, players in d.get('players', {}).items():
                for player in players:
                    player_data = {"match_id": matchID, "person_id": registry.get(player, None), "team_name": team}
                    insert_dict_into_database(player_data, "players", engine)
            print("crossed players, ",matchID)

            # ✅ Insert `deliveries` (Direct Dict Inserts)
            for inning_count, inning in enumerate(data.get('innings', []), start=1):
                for over in inning.get('overs', []):
                    for ball_count, delivery in enumerate(over.get('deliveries', []), start=1):
                        delivery_data = {
                            "match_id": matchID,
                            "innings": inning_count,
                            "team": inning.get("team"),
                            "overs": over.get("over"),
                            "balls": ball_count,
                            "batter": registry.get(delivery.get("batter")),
                            "bowler": registry.get(delivery.get("bowler")),
                            "non_striker": registry.get(delivery.get("non_striker")),
                            "runs_batter": delivery.get("runs", {}).get("batter"),
                            "runs_extras": delivery.get("runs", {}).get("extras"),
                            "runs_total": delivery.get("runs", {}).get("total"),
                            "player_out": registry.get(delivery.get("wickets", [{}])[0].get("player_out")),
                            "dismissal_kind": delivery.get("wickets", [{}])[0].get("kind")
                        }
                        insert_dict_into_database(delivery_data, "deliveries", engine)
            print("crossed deliveries", matchID)
            return matchID

    except Exception as e:
        #print(f"❌ Error processing {filepath}: {e}")
        logging.error(f"Error processing {filepath}: {e}")  # Log file processing errors
        return None

def process_all_json_files_parallel(matches_path, formats, num_workers=50):
    """ Process JSON files in parallel using ThreadPoolExecutor. """
    all_files = []

    for format_name in formats:
        format_path = os.path.join(matches_path, format_name)
        if os.path.isdir(format_path):
            files = [os.path.join(format_path, file) for file in os.listdir(format_path) if file.endswith(".json")]
            all_files.extend(files)
    print("Inside process_all_json_files_parallel", all_files)

    # ✅ Process files in parallel (limit to `num_workers` threads)
    with ThreadPoolExecutor(max_workers=num_workers) as executor:
        results = list(executor.map(process_json_file, all_files))

    print(f"✅ Processed {len([r for r in results if r is not None])} matches successfully!")

# Example Usage:
matches_path = "matches"
formats = ["sample"]
process_all_json_files_parallel(matches_path, formats, num_workers=50)