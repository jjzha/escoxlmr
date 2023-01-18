import math


class Perplexity:
    def __init__(self):
        self.sum = 0
        self.number = 0
        self.str = 'perplexity'

    def score(self, loss):
        self.sum += loss
        self.number += 1

    def reset(self):
        self.sum = 0
        self.number = 0

    def get_score(self):
        if self.sum == 0:
            return self.str, 0.0
        return self.str, math.exp(self.sum / self.number)
