import requests
from scipy.stats import rankdata
import statistics
import csv

### League Metadata
# League ID is visible in league settings or browser URL if on computer
LEAGUE_ID = 1021898570066784256 
# Populate this manually. This is the week that you just finished or want to represent.
LATEST_FINISHED_WEEK = 1

### Sleeper API endpoints
GET_LEAGUE_ENDPOINT = 'https://api.sleeper.app/v1/league/{}'
GET_USERS_ENDPOINT = "https://api.sleeper.app/v1/league/{}/users"
GET_MATCHUPS_ENDPOINT = "https://api.sleeper.app/v1/league/{}/matchups/{}"
GET_ROSTERS_ENDPOINT = "https://api.sleeper.app/v1/league/{}/rosters"

### Weights for power ranking factors
### Can play around with these values as you like

WIN_WEIGHT_EARLY_SEASON = 1.2*LATEST_FINISHED_WEEK # Default = 1.2*LATEST_FINISHED_WEEK
WIN_WEIGHT = 3 # Default = 3
WIN_EARLY_SEASON_WEEK_THRESHOLD = 3 # Default = 3

OVERALL_WIN_WEIGHT = 2 # Default = 2

RECENT_WINS_WEIGHT_EARLY_SEASON = 0 # Default = 0
RECENT_WINS_WEIGHT = 1.5 # Default = 1.5
RECENT_WINS_EARLY_SEASON_WEEK_THRESHOLD = 8 # Default = 8
RECENT_WEEKS_COUNT = 5 # Default = 5

CONSISTENCY_WEIGHT_EARLY_SEASON = 0 # Default = 0
CONSISTENCY_WEIGHT = 0.5 # Default = 0.5
CONSISTENCY_EARLY_SEASON_WEEK_THRESHOLD = 3 # Default = 3

POINTS_SCORED_WEIGHT = 1 # Default = 1

ROSTER_STRENGTH_WEIGHT = 1.5 # Default = 1.5

### Stored Data
ROSTER_TO_TEAM_NAME_MAPPING = {}

# PER_TEAM_WEEKLY_MATRIX_DATA is populated in the following way:
# 
# {
#     "roster-id-0": [PerRosterWeeklyData(week1), PerRosterWeeklyData(week2), PerRosterWeeklyData(week3)...],
#     "roster-id-1": [PerRosterWeeklyData(week1), PerRosterWeeklyData(week2), PerRosterWeeklyData(week3)...],
#     ...
# }
# 
# This way we should be able to just index based on week number easily
PER_TEAM_WEEKLY_MATRIX_DATA = {}

# FINAL_RESULTS is populated in the following way:
# 
# {
#     "roster-id-0": PerRosterCalculatedData,
#     "roster-id-1": PerRosterCalculatedData,
#     ...
# }
# 
FINAL_RESULTS = {}

class PerRosterWeeklyData:
    def __init__(self, points_scored, matchup_id):
        self.points_scored = points_scored
        self.matchup_id = matchup_id

class PerRosterCalculatedData:
    def __init__(self):
        pass

def main():
    # Load in all necessary data
    populate_roster_to_team_name_mapping()
    populate_per_roster_data()

    # Gather individual calculations
    points_per_game_rankings, consistency_rankings = calculate_points_per_game_and_consistency_rankings()
    wins_rankings, overall_wins_rankings, recent_wins_rankings = calculate_wins_and_overall_wins_and_recent_wins_rankings()
    ros_rankings = get_ros_rankings()

    # Calculate and sort power rankings
    calculate_power_rankings_per_team(wins_rankings, overall_wins_rankings, recent_wins_rankings, points_per_game_rankings, consistency_rankings, ros_rankings)

    # Export to CSV
    export_to_csv()

# Load in data and map roster IDs to team names and set global map
def populate_roster_to_team_name_mapping():
    user_to_team_name = {}
    roster_to_user = {}

    users_info = requests.get(GET_USERS_ENDPOINT.format(LEAGUE_ID)).json()
    for user in users_info:
        user_to_team_name[user['user_id']] = user['display_name']
    
    rosters_info = requests.get(GET_ROSTERS_ENDPOINT.format(LEAGUE_ID)).json()
    for roster in rosters_info:
        roster_to_user[roster['roster_id']] = roster['owner_id']

    for roster in roster_to_user.keys():
        ROSTER_TO_TEAM_NAME_MAPPING[roster] = user_to_team_name[roster_to_user[roster]]

# Populate PER_TEAM_WEEKLY_MATRIX_DATA with the necessary data for each teams weekly matchups
# Check the global definition for PER_TEAM_WEEKLY_MATRIX_DATA to see how data is organized here
def populate_per_roster_data():
    for i in range(0, LATEST_FINISHED_WEEK):
        matchups_for_week = requests.get(GET_MATCHUPS_ENDPOINT.format(LEAGUE_ID, i+1)).json()
        for roster in matchups_for_week:
            roster_data = PerRosterWeeklyData(roster["points"], roster["matchup_id"])
            if roster["roster_id"] in PER_TEAM_WEEKLY_MATRIX_DATA.keys():
                PER_TEAM_WEEKLY_MATRIX_DATA[roster["roster_id"]].append(roster_data)
            else:
                PER_TEAM_WEEKLY_MATRIX_DATA[roster["roster_id"]] = [roster_data]

# Calculate wins, overall wins, and recent wins. Sleeper API makes this a little complicated but it looks something like:
# 
# For each team:
#   For each week:
#       1. compare the current teams score with every other teams score to gather overall record
#       2. Find the corresponding matchup ID among the other teams in the league (should only be 1 other team), and record a win if necessary
#       3. If within the recent wins bound, then record a win (step 2) as a recent win as well
#
# It would be useful to understand how PER_TEAM_WEEKLY_MATRIX_DATA is formatted. Check the global instantiation above.
# Also useful to see how the sleeper matchups API works https://docs.sleeper.app/#getting-matchups-in-a-league
def calculate_wins_and_overall_wins_and_recent_wins_rankings():
    overall_wins = {}
    wins = {}
    recent_wins = {}

    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        overall_wins[roster_id] = 0
        wins[roster_id] = 0
        recent_wins[roster_id] = 0

    recent_week_threshold = LATEST_FINISHED_WEEK - RECENT_WEEKS_COUNT

    for i in range(0, LATEST_FINISHED_WEEK):
        for roster_id, roster_data in PER_TEAM_WEEKLY_MATRIX_DATA.items():
            for other_roster_id, other_roster_data in PER_TEAM_WEEKLY_MATRIX_DATA.items():
                # Do not want to compare against ourself
                if roster_id is not other_roster_id:
                    overall_wins[roster_id] += 1 if roster_data[i].points_scored > other_roster_data[i].points_scored else 0
                    # If we find the other team with the same matchup ID, this means we found who we truly
                    # played this week. So we will also include this data for our wins and recent wins calculation.
                    if roster_data[i].matchup_id == other_roster_data[i].matchup_id:
                        wins[roster_id] += 1 if roster_data[i].points_scored > other_roster_data[i].points_scored else 0
                        if i >= recent_week_threshold and recent_week_threshold >= 0:
                            recent_wins[roster_id] += 1 if roster_data[i].points_scored > other_roster_data[i].points_scored else 0

    sorted_wins = dict(sorted(wins.items(), key=lambda item: item[1]))
    sorted_overall_wins = dict(sorted(overall_wins.items(), key=lambda item: item[1]))
    sorted_recent_wins = dict(sorted(recent_wins.items(), key=lambda item: item[1]))

    ranked_wins = rank_data_keyed_by_roster_id(sorted_wins, 0)
    ranked_overall_wins = rank_data_keyed_by_roster_id(sorted_overall_wins, 0)
    ranked_recent_wins = rank_data_keyed_by_roster_id(sorted_recent_wins, 0)

    # Write results to global results data structure
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        if roster_id not in FINAL_RESULTS.keys():
            FINAL_RESULTS[roster_id] = PerRosterCalculatedData()
        
        FINAL_RESULTS[roster_id].wins = sorted_wins[roster_id]
        FINAL_RESULTS[roster_id].wins_rankings = ranked_wins[roster_id]
        FINAL_RESULTS[roster_id].overall_wins = sorted_overall_wins[roster_id]
        FINAL_RESULTS[roster_id].overall_wins_rankings = ranked_overall_wins[roster_id]
        FINAL_RESULTS[roster_id].recent_wins = sorted_recent_wins[roster_id]
        FINAL_RESULTS[roster_id].recent_wins_rankings = ranked_recent_wins[roster_id]

    return ranked_wins, ranked_overall_wins, ranked_recent_wins

# Iterate through all teams and weeks to add up and calculate team based PPG
#
# Calculate consistency rankings using the coefficient of variation:
# Team StdDev / Team Average
# Calculate consistency as 0 if before CONSISTENCY_EARLY_SEASON_WEEK_THRESHOLD
def calculate_points_per_game_and_consistency_rankings():
    points_per_roster = {}
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        points_per_roster[roster_id] = []
    
    for i in range(0, LATEST_FINISHED_WEEK):
        for roster_id, roster_data in PER_TEAM_WEEKLY_MATRIX_DATA.items():
            points_per_roster[roster_id].append(roster_data[i].points_scored)

    points_per_game_per_roster = {}
    std_dev_per_game_per_roster = {}

    for roster_id, points_scored_per_week in  points_per_roster.items():
        points_per_game_per_roster[roster_id] = statistics.mean(points_scored_per_week)

        # Need multiple data points (multiple weeks) to calculate Std Dev. So lets just only calculate it
        # when we pass our defined weekly threshold, and leave it as 0 otherwise since it will not
        # be included in the final power ranking calculation anyways
        if LATEST_FINISHED_WEEK >= CONSISTENCY_EARLY_SEASON_WEEK_THRESHOLD:
            std_dev_per_game_per_roster[roster_id] = statistics.stdev(points_scored_per_week)
        else:
            std_dev_per_game_per_roster[roster_id] = 0

    ranked_points_per_game = rank_data_keyed_by_roster_id(points_per_game_per_roster, 0)

    consistency_per_roster = {}
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        consistency_per_roster[roster_id] = std_dev_per_game_per_roster[roster_id] / points_per_game_per_roster[roster_id]

    ranked_consistency = rank_data_keyed_by_roster_id(consistency_per_roster, 1)

    # Write results to global results data structure
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        if roster_id not in FINAL_RESULTS.keys():
            FINAL_RESULTS[roster_id] = PerRosterCalculatedData()
            
        FINAL_RESULTS[roster_id].points_per_game = points_per_game_per_roster[roster_id]
        FINAL_RESULTS[roster_id].points_per_game_rankings = ranked_points_per_game[roster_id]
        FINAL_RESULTS[roster_id].consistency = consistency_per_roster[roster_id]
        FINAL_RESULTS[roster_id].consistency_rankings = ranked_consistency[roster_id]

    return ranked_points_per_game, ranked_consistency

# Get ROS rankings for roster strength. This is a manual step and requires human input. ROS roster strength can be found
# on FantasyPros    
def get_ros_rankings():
    ros_rankings = {}
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        ros_rankings[roster_id] = int(input("ROS Ranking for {}: ".format(ROSTER_TO_TEAM_NAME_MAPPING[roster_id])))

    # Write results to global results data structure
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        if roster_id not in FINAL_RESULTS.keys():
            FINAL_RESULTS[roster_id] = PerRosterCalculatedData()
            
        FINAL_RESULTS[roster_id].ros_rankings = ros_rankings[roster_id]

    return ros_rankings

# The formula to calculate the power rankings is as follows:
#
# power_rank_for_team = num/den
# where
# num = (Record Rank * Win weight) + (OVW rank * OWV weight) + (Recent wins rank * RecentWinWeight) + 
# (Consistency rank * Consitency weight) + (PPG rank * PPG weight) + (Roster ROS rank * ROS weight)
# and
# den = Win weight + OWV weight + RecentWinWeight + Consitency weight + ROS weight
#
# Note that the weights change based on current time in the season. Check the global constants to see how they are defined, and to modify them.
def calculate_power_rankings_per_team(wins_rankings, overall_wins_rankings, recent_wins_rankings, points_per_game_rankings, consistency_rankings, ros_rankings):
    power_rankings = {}

    WIN_WEIGHT_TO_USE = WIN_WEIGHT if LATEST_FINISHED_WEEK >= WIN_EARLY_SEASON_WEEK_THRESHOLD else WIN_WEIGHT_EARLY_SEASON
    RECENT_WINS_TO_USE = RECENT_WINS_WEIGHT if LATEST_FINISHED_WEEK >= RECENT_WINS_EARLY_SEASON_WEEK_THRESHOLD else RECENT_WINS_WEIGHT_EARLY_SEASON
    CONSISTENCY_TO_USE = CONSISTENCY_WEIGHT if LATEST_FINISHED_WEEK >= CONSISTENCY_EARLY_SEASON_WEEK_THRESHOLD else CONSISTENCY_WEIGHT_EARLY_SEASON

    print("Using the following weights: \nWins: {} \nOverall Wins: {}\nRecent Wins: {}\nConsistency: {}\nPoints per Game: {}\nROS Rank: {}".format(WIN_WEIGHT_TO_USE, OVERALL_WIN_WEIGHT, RECENT_WINS_TO_USE, CONSISTENCY_TO_USE, POINTS_SCORED_WEIGHT, ROSTER_STRENGTH_WEIGHT))
        
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        num = (wins_rankings[roster_id] * WIN_WEIGHT_TO_USE) + (overall_wins_rankings[roster_id] * OVERALL_WIN_WEIGHT) + (recent_wins_rankings[roster_id] * RECENT_WINS_TO_USE) + (points_per_game_rankings[roster_id] * POINTS_SCORED_WEIGHT) + (consistency_rankings[roster_id] * CONSISTENCY_TO_USE) + (ros_rankings[roster_id] * ROSTER_STRENGTH_WEIGHT)
        den = WIN_WEIGHT_EARLY_SEASON + OVERALL_WIN_WEIGHT + POINTS_SCORED_WEIGHT + ROSTER_STRENGTH_WEIGHT
        power_rankings[roster_id] = round(num/den, 2)

    power_rankings_ranked = rank_data_keyed_by_roster_id(power_rankings, 1)

    # Write results to global results data structure
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        if roster_id not in FINAL_RESULTS.keys():
            FINAL_RESULTS[roster_id] = PerRosterCalculatedData()
            
        FINAL_RESULTS[roster_id].power_rankings = power_rankings[roster_id]
        FINAL_RESULTS[roster_id].power_rankings_rankings = power_rankings_ranked[roster_id]

# Helper to convert and dict mapped on roster IDs to an equal dict with usernames as the keys
def convert_roster_keyed_dict_to_username_mapping(to_convert):
    new_dict = {}
    for convertable_roster_id, value in to_convert.items():
        new_dict[ROSTER_TO_TEAM_NAME_MAPPING[convertable_roster_id]] = value
    return new_dict

# Helper to take a linear data structure (or a map where values need to be ranked) and to return
# a ranked version of the same data structure.
#
# e.g rankdata([0, 2, 3, 2], method='min')
# array([ 1,  2,  4,  2])
# See https://docs.scipy.org/doc/scipy/reference/generated/scipy.stats.rankdata.html
def rank_data_keyed_by_roster_id(to_rank, to_reverse):
    rank_matrix = []
    reverse_items = -1 if to_reverse == 0 else 1

    for roster_id, value in to_rank.items():
        rank_matrix.append([roster_id, reverse_items*value])
    
    ranked_data = rankdata(rank_matrix, axis=0, method='min')

    rebuilt_to_roster_id = {}
    for item in ranked_data:
        rebuilt_to_roster_id[item[0]] = item[1]

    return rebuilt_to_roster_id 

# Aggregate data from FINAL_RESULTS and format/write to CSV
def export_to_csv():
    final_results = []
    for roster_id in ROSTER_TO_TEAM_NAME_MAPPING.keys():
        roster_results = {}

        roster_results['POWER RANK'] = FINAL_RESULTS[roster_id].power_rankings_rankings
        roster_results['POWER RANK VALUE'] = FINAL_RESULTS[roster_id].power_rankings

        roster_results['Member'] = ROSTER_TO_TEAM_NAME_MAPPING[roster_id]

        roster_results['PPG'] = FINAL_RESULTS[roster_id].points_per_game
        roster_results['PPG Rank'] = FINAL_RESULTS[roster_id].points_per_game_rankings

        roster_results['Wins'] = FINAL_RESULTS[roster_id].wins
        roster_results['Win Rank'] = FINAL_RESULTS[roster_id].wins_rankings

        roster_results['Overall Wins'] = FINAL_RESULTS[roster_id].overall_wins
        roster_results['Overall Win Rank'] = FINAL_RESULTS[roster_id].overall_wins_rankings

        roster_results['Recent Wins'] = FINAL_RESULTS[roster_id].recent_wins
        roster_results['Recent Wins Rank'] = FINAL_RESULTS[roster_id].recent_wins_rankings

        roster_results['Consistency Rating'] = FINAL_RESULTS[roster_id].consistency
        roster_results['Consistency Rank'] = FINAL_RESULTS[roster_id].consistency_rankings
        
        roster_results['ROS Roster Rank'] = FINAL_RESULTS[roster_id].ros_rankings
        final_results.append(roster_results)
    
    field_names = ['POWER RANK', 'Member', 'POWER RANK VALUE', 'PPG', 'PPG Rank', 'Wins', 'Win Rank', 'Overall Wins', 'Overall Win Rank', 'Recent Wins', 'Recent Wins Rank',
     'Consistency Rating', 'Consistency Rank', 'ROS Roster Rank',]
    with open('Week-{}-Power-Rankings.csv'.format(LATEST_FINISHED_WEEK), 'w') as csvfile:
        writer = csv.DictWriter(csvfile, fieldnames = field_names)
        writer.writeheader()
        writer.writerows(final_results)

if __name__ == "__main__":
    main()
