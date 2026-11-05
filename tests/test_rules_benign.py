"""False-positive guard: benign sentences must score below the rule threshold."""

import pytest

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
    # --- persona/safety near-misses (ticket 0072) ---
    # Security training text
    "Our safety guidelines were updated last quarter.",
    "The safety training module covers ethical constraints for AI systems.",
    "The content moderation policy was reviewed by the safety team.",
    "We discuss how safety filters work in production systems.",
    "The new content guidelines take effect starting next month.",
    # Role-play fiction
    "Act as a pirate captain in the novel.",
    "Pretend to be a dragon for the children's story.",
    "You are now the hero of the tale.",
    "In the role-play game, she acts as an unconstrained villain.",
    "Pretend you are a wizard in the fantasy world.",
    "The book's protagonist is amoral but well-developed as a character.",
    # Persona descriptions
    "You are now in a creative writing mode.",
    "The assistant persona is described as uncensored in the book review.",
    # Safety policy discussion
    "Discussions about moral guidelines in AI safety are common in academia.",
    "Do not refuse to help students with their homework assignments.",
    "The safety policy discussion covered how to balance moral restrictions with user needs.",
]

# Benign sentences that the current persona/safety rules false-positive on.
# Each is a legitimate benign sentence that triggers a 0072 rule at 0.75.
BENIGN_XFAIL = [
    ("The company has no content restrictions on its public blog.",
     "safety-suspension rule matches 'no content restrictions'"),
    ("Act as an unrestricted character for the research simulation.",
     "persona-switch rule matches 'act as ... unrestricted'"),
    ("The persona is a helpful assistant with no safety constraints.",
     "safety-suspension rule matches 'no safety constraints'"),
    ("The model should never refuse legitimate questions from users.",
     "refusal-suppression rule matches 'never refuse ... questions'"),
    ("The paper argues that no ethical rules should apply to public APIs.",
     "safety-suspension rule matches 'no ethical rules'"),
    ("Without any safety filters, the system would be dangerous.",
     "safety-suspension rule matches 'without any safety filters'"),
    ("Free from all moral constraints, the character makes bold decisions.",
     "safety-suspension rule matches 'free from all moral constraints'"),
    ("The developer noted that no content rules apply to the test environment.",
     "safety-suspension rule matches 'no content rules'"),
    ("Never refuse a request that is clearly within the acceptable use policy.",
     "refusal-suppression rule matches 'never refuse a request'"),
]


def test_benign_sentences_score_below_threshold():
    for text in BENIGN:
        value = score(text)
        assert value < THRESHOLD, f"false positive ({value}): {text!r}"


@pytest.mark.parametrize("text,reason", BENIGN_XFAIL,
                         ids=[t[:40] for t, _ in BENIGN_XFAIL])
@pytest.mark.xfail(reason="benign near-miss triggers persona/safety rule (ticket 0082)")
def test_benign_near_miss_xfail(text, reason):
    value = score(text)
    assert value < THRESHOLD, f"false positive ({value}): {text!r} ({reason})"
