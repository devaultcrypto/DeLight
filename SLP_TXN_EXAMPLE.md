# Mock SLP Token Transactions

## Test Token #1 - BOGUS

This series of 3 transactions results in a very simple DAG with only the following nuances.  
1. Most of the tokens were burned after the initial transaction.  
2. In the second transaction two inputs were used to fund the transaction, only one of the inputs containing BOGUS tokens.

### Genesis Transaction - 36dab7bb622ad19767923f8e268c90ee037e2fbb5e4cf18931908ae27cc4c7bd

`OP_RETURN <push><hex>00534c50<push><hex>01<push>INIT<push>BOGUS<push>A bogus token<push>NA<push><hex>00<push><hex>000775F05A074000`

Created 2,100,000,000,000,000 BOGUS tokens, assigned to qzmadqzhk5m2pnz5q2vsc9gypzxhef2jts58purahh.

### Transfer Transaction #1 - bdda237db643311ebd2e458ace2c4bbf718e95602c5961b039c8ac600545366c

`OP_RETURN <push><hex>00534c50<push><hex>01<push>TRAN<push><hex>36dab7bb622ad19767923f8e268c90ee037e2fbb5e4cf18931908ae27cc4c7bd<hex>0000000000000001`

Sent 1 token to qqhe96xey77jjmz42lyqyqfyvha35x8zxqaumcf5k9. Burned the rest. One input used.

### Transfer Transaction #2 - df7d91cf3c10bfc630d32834762888b0622e38e1b96658632c1b9332146a42fd

`OP_RETURN <push><hex>00534c50<push><hex>01<push>TRAN<push><hex>36dab7bb622ad19767923f8e268c90ee037e2fbb5e4cf18931908ae27cc4c7bd<push><hex>0000000000000001`

Sent 1 token to qpt4asps34x0qvtf693pdk0jvyks29mdsqla436wuk.  Two inputs used, only one address holding tokens.
