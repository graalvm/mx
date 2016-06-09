
# Styleguide

This document describes the styleguide conventions in the `mx` codebase.

Note that legacy `mx` code may not in all cases adhere to the conventions in this doc,
but new code submitted to `mx` should nevertheless follow the guidelines.


## Python

### Doc comments

Doc comments for modules, classes and methods should use the
[*reStructuredText Docstring Format*](https://www.python.org/dev/peps/pep-0287/),
and [Sphinx documentation syntax](http://www.sphinx-doc.org/en/stable/domains.html)
for type annotations. There's also a great
[cheat sheet](http://thomas-cokelaer.info/tutorials/sphinx/rest_syntax.html) to get started.

Quick example:

    """This module contains the common utility functions and classes necessary
    for a lottery business."""

    class Lottery(object):
        """An object that encodes the core logic for a lottery business.

        :param float maximumReward: A maximum monetary reward that a person can get.
        """

        def __init__(self, maximumReward):
            self.maximumReward = maximumReward

        def riggedLottery(self, winningTicket, participants, reward):
            """Deterministically returns a lottery winner.

            :Example:

                obj.riggedLottery(1, ["Jack", "Jill"],
                    "When you're out to fetch some water, don't forget your bucket.")

            :param int winningTicket: Your lucky number.
            :param list participants: A list of awesome participants.
            :param reward: A reward for the winner (money amount, or voucher code).
            :type reward: float or str
            :return: A tuple with the lucky winner and his reward.
            :rtype: tuple
            :raises IndexError:
                If the winning ticket number is greater than the number of participants,
                an error is thrown. This requires a long explanation, so we start the
                description in a new line and indent it.
            """
            if type(reward) is float:
                reward = min(reward, self.maximumReward)
            return participants[winningTicket], reward

Some guidelines:

- Start your doc comments sentences with a capital letter, and use proper punctuation.
- If a doc is one-liner, you should start and end the triple quote in the same line.
- Unless a multi-line doc string describes a module, the ending triple quote should be
  on a separate line.
- Start the doc comment with a short one-line summary.
- Subsequent paragraphs describe the semantics in more detail.
- Use Sphinx syntax to describe parameters and return values.
- If a parameter has one possible (super)type, use the one-line description.
  Only if you must enumerate multiple types, use the both `:param` and `:type`
  annotations.

For generators, the return description is used to encode the yield value:

    :return: A generator over instances of :class:`MyClass`
    :rtype: :class:`types.GeneratorType`
