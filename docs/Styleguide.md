
# Styleguide

This document describes the styleguide conventions in the `mx` codebase.

Note that legacy `mx` code may not in all cases adhere to the conventions in this doc,
but new code submitted to `mx` should nevertheless follow the guidelines.


## Python

### Code Style

Code is formatted using [*Black*](https://github.com/psf/black).
Formatting can be done manually using `mx pyformat`; this will format all eligible python files in this repository.
It is recommended to set up auto-formatting in your [IDE](./IDE.md) to avoid formatting-only commits.

Only new python files are formatted; which files are excluded is specified in [`pyproject.toml`](../pyproject.toml)
under `force-exclude`.

To ensure a consistent style, the major version of *Black* is fixed in [`pyproject.toml`](../pyproject.toml).
Other major versions (newer or older) cannot be used as they could lead to slightly different formatting, failing the
code format check in the CI.
See also [*Black*'s Stability Policy](https://black.readthedocs.io/en/stable/the_black_code_style/index.html).

#### In Suite Code

`mx pyformat` is also available to suites and is run in the style gate (guarded by `mx_compat`).

Not all suites may be ready/want to format all their python files (because it would cause large diffs, making looking at
git history difficult).
This especially applies to auto-formatting done in the IDE.

Formatting can be disabled for entire folders by creating a `pyproject.toml` with the following content:

```toml
[tool.black]
force-exclude = '.*'
```

This is a regex pattern and can also be tweaked to only exclude certain files.

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
