"""False-positive guard: benign sentences must score below the rule threshold."""

from data_processing.rules import score

THRESHOLD = 0.5

BENIGN = [
    "Please ignore the notification badge on your phone.",
    "The system was upgraded last night without any issues.",
    "Follow the instructions in the user manual.",
    "I forgot the instructions for the new app somewhere.",
    "The recipe says to ignore the skin on the chicken legs.",
    "Our company has strict rules about remote work policies.",
    "The guidelines were updated last quarter by the legal team.",
    "Please do not bypass the security checkpoint at the entrance.",
    "The system administrator will reset your password tomorrow.",
    "I need to override the default settings in my editor.",
    "The prompt engineering course starts on Monday morning.",
    "She wrote a prompt for the art installation.",
    "Ignore the broken link at the bottom of the page.",
    "The instructions on the box say to preheat the oven.",
    "Our system uses a load balancer to distribute traffic.",
    "Please disregard the outdated information in that document.",
    "The rules of the game are explained in the first chapter.",
    "I bypassed the toll booth by taking the back road.",
    "The policy was reviewed by the compliance team.",
    "Can you forget about that meeting and focus on this task?",
    "The guidelines for submitting papers are on the website.",
    "He ignored the instructions on the package and it worked fine.",
    "The system prompt in the documentation is just an example.",
    "Please ignore the advertisement at the top of the page.",
    "The new rules take effect starting next month.",
    "I need to override the system settings for my monitor.",
    "The instructions manual is available at the front desk.",
    "She forgot the rules for the card game we played last week.",
    "The policy document is in the shared drive folder.",
    "Please bypass the main entrance and use the side door.",
]


def test_benign_sentences_score_below_threshold():
    for text in BENIGN:
        value = score(text)
        assert value < THRESHOLD, f"false positive ({value}): {text!r}"
