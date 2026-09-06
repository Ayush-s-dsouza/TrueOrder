# RUNBOOK — how a person actually does this today

This is what happens today when someone with a mixed debt portfolio — a
couple of credit cards, an EMI or two, maybe a home loan — tries to figure
out what order to pay things off in. It is not a description of how to run
this repo.

## Step 1

You Google "avalanche vs snowball debt repayment" or "how to pay off debt
fastest." Every result explains the same two methods: avalanche (highest
interest rate first) and snowball (smallest balance first). Almost all of
them recommend avalanche as mathematically optimal.

## Step 2

You list your debts and their stated interest rates from memory or by
opening each app. Nobody's app shows all of them side by side, so this list
lives in your head or a notes app, not anywhere that gets checked for
mistakes.

## Step 3

You sort the list by rate, highest first. This is where the naive avalanche
order comes from — and it's the entire analysis. Nothing about tax
treatment, prepayment charges, or how paying off one card versus another
affects your credit utilisation ever enters the picture, because nothing in
step 1 or step 2 raised it.

## Step 4

If you use an AI assistant instead — asking Dhruva directly "I have 5 EMIs
and 4 credit cards, what order should I repay them in?" — you get exactly
the avalanche answer from step 3, restated in prose. No question about your
tax regime, no question about whether a property is self-occupied or
rented out, no mention that a floating-rate loan and a fixed-rate loan
carry very different prepayment consequences.

## Step 5

You check whether your budgeting or credit-monitoring app does any better.
For Oolka specifically, the premium tier is utilisation alerts and bureau
dispute automation — genuinely useful, but not avalanche/snowball
optimization and not lump-sum-split guidance across a portfolio. The gap
this runbook is describing isn't filled by upgrading.

## Step 6

You repay debts in the naive avalanche order. For an all-unsecured,
same-tax-treatment portfolio this is often fine — avalanche isn't wrong in
general. It's wrong specifically when: a home loan's real deduction depends
on which tax regime you're in and whether the property is self-occupied or
let out; a fixed-rate loan carries a real foreclosure charge that a
floating-rate loan of the same stated APR does not; or clearing one credit
card versus another crosses a utilisation threshold that affects your
credit score in a way no interest-rate comparison captures. Nobody's
process today checks for any of these before committing to an order.

## What this process actually costs

- **A wrong order compounds silently.** Paying down a tax-advantaged home
  loan before a fixed-rate auto loan with a real foreclosure charge, purely
  because the home loan's stated rate looks worse, can mean paying more
  total interest and a foreclosure fee that a correctly-sequenced plan
  would have avoided or minimized.
- **The tax question is binary and often gotten wrong by assumption.**
  Whether Section 24(b) or Section 80E actually applies depends on regime
  and, for home loans, occupancy — get either wrong and the "optimal" order
  is optimizing against a deduction that doesn't exist.
- **Utilisation tension is invisible to a rate-only comparison.** A card
  sitting just above the 30%-aggregate-utilisation line has a real
  credit-score cost that no avalanche/snowball ranking accounts for at all.

TrueOrder automates steps 1–3 and 6 into one call: it takes the same
portfolio a person would type into Dhruva, computes the naive order exactly
as today's tools do, and computes a tax-and-fee-adjusted order alongside it
— showing where and why the two disagree, with every adjustment traced back
to the specific rule and source that produced it.
