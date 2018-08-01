# Mock SLP Token Transactions

## Test Token #1

This series of 3 transactions results in a very simple DAG with only the following nuances.  
1. Most of the tokens were burned after the initial transaction.  
2. In the second transaction two inputs were used to fund the transaction, only one of the inputs containing BOGUS tokens.

### Genesis Transaction

Example OP_RETURN tool msg = 
`<push><hex>00534c50<push><hex>01<push>INIT<push><empty><push><empty><push><empty><push><empty><push><hex>00<push><hex>000000F05A074000`

### Transfer Transaction #1

Example OP_RETURN tool msg = `<push><hex>00534c50<push><hex>01<push>TRAN<push><hex>36dab7bb622ad19767923f8e268c90ee037e2fbb5e4cf18931908ae27cc4c7bd<push><hex>0000000000000001`

### Transfer Transaction #2

Example OP_RETURN tool msg = `<push><hex>00534c50<push><hex>01<push>TRAN<push><hex>36dab7bb622ad19767923f8e268c90ee037e2fbb5e4cf18931908ae27cc4c7bd<push><hex>0000000000000001`
