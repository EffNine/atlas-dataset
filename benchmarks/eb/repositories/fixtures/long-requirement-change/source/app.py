class Counter:
    def __init__(self):
        self._value = 0

    def increment(self):
        self._value += 1

    def get_value(self):
        return self._value
