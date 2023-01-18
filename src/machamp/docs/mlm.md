### mlm task-type

[back to main README](../README.md)

The task-type `mlm` can be used for Masked Language Modeling. In MaChAmp, we follow the strategy of the original BERT
paper ([Devlin et al, 2019](https://www.aclweb.org/anthology/N19-1423/)), except that we do not use the next sentence
prediction. The input data for this task should be in raw txt format, like this (this is a sample from Wikipedia):

```
Alvestêdetocht
De Alvestêdetocht is in reedriderstocht fan sawat 200 kilometer by de alve stêden fan Fryslân lâns. 
Ljouwert, de haadstêd fan Westerlauwersk Fryslân, is fan âlds it start- en finishplak. 
De tocht bringt de dielnimmers fan Ljouwert nei Snits, Drylts, Sleat, Starum, Hylpen, Warkum, Boalsert, Harns, Frjentsjer en Dokkum en dan wer werom nei Ljouwert, dêr't op de Bonke de einstreek leit. 
Hûnderttûzenen taskôgers wiene by de lêste tochten de kjeld treast en moedigen oan 'e rûte de reedriders oan.
```

The only supported evaluation metric for this task is perplexity. Because in multi-task learning we pick the model with
the highest sum of all metrics and most metrics have a range 0-1, we invert the perplexity by doing: `1-1/ppl`. This can
easily be edited in the bottom of `machamp/models/machamp_model.py`, and we welcome suggestions on how to do this more
correct/principled.

Furthermore, it should be noted that we saw in some of our experiments, that performance on the development set only
increased after the first epoch. This led to the model always picking a very early model. Hence, we got much better
performance by not defining a development set for MLM, and thus not using perplexity to pick the best model.

