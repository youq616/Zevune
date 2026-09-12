# DRAFT-01：网络域绑定的交易授权候选

状态：实现与测试候选，**未在现有钱包、PoolStore、Go/Rust 状态进程或 CometBFT 网络激活**。不是主网协议定稿，不是独立审计。旧 `ZVORLAB1` 的签名、账本和钱包文件保持不变；新代码不迁移旧数据、不广播、不发行资产。

## 1. 解决的问题与不解决的问题

旧实验签名绑定固定字符串 `zevune-orchard-lab-1`、费用、过期高度和 Orchard V5 bundle commitment，但没有独立的创世/规则/纪元标识。不能仅凭外面加一个网络标签，就声称既有签名不能跨环境使用。

候选新增明确的签名域，付款授权同时绑定网络类别、创世承诺、规则承诺、协议纪元与固定密码套件。即使两套环境具有相同的资产树根，一份签名也不能只修改外层网络标签就变成另一签名域的有效授权。本轮测试用真正的 Orchard 证明与签名验证这一性质，不把哈希不同当作签名拒绝的替代证据。

这里并不定义正式创世分配、奖励和手续费归属，不解决 IP、交易时序、设备入侵或监管问题。也不防止相同域中的重复花费：这一点仍由可信账本的 nullifier 状态处理。完整复制相同域描述符和信任根，就是相同网络身份，不是不同网络；本方案不会把这种克隆自动识别成新链。

## 2. 域描述符：固定 79 字节

所有整数无符号大端。所有字段都参加域哈希；没有可忽略字段、尾部扩展、Unicode 名称或可选默认值。

| 偏移 | 长度 | 内容 |
|---|---:|---|
| 0 | 8 | ASCII `ZVDOM001` |
| 8 | 1 | 类别：1=开发，2=测试；其他值拒绝，尚无主网类别 |
| 9 | 32 | 非全零创世承诺 |
| 41 | 32 | 非全零规则承诺 |
| 73 | 4 | 非零协议纪元 |
| 77 | 2 | 套件=1，其他值拒绝 |

套件 1 明确对应已锁定 Orchard V2、FixedPostNu6_2 验证密钥和 V5 bundle commitment；不能由交易发送者传入证明验证密钥或切换到旧不安全电路。

```text
domain_id = SHA256(ASCII("ZEVUNE-DOMAIN") || 00 || 01 || descriptor_79)
```

调用者必须从独立可信的引导配置取得预期描述符。不能先读取交易携带的域，再将其当作预期域。32 字节承诺是对外部已审查定义的引用，不代表描述符解码器验证了创世或规则文件。未来激活必须冻结这两份承诺的原文与规范编码，不得对包含该域 ID 的最终创世 JSON 再哈希形成循环定义。

纪元不同产生不同授权域，但本库不决定何时升级。高度选择、分叉规则、回退和旧钱包迁移必须经过单独的确定性激活设计。

## 3. 签名摘要

```text
signature_digest = SHA256(
    ASCII("ZEVUNE-TX-SIGHASH") || 00 || 01 ||
    domain_id_32 || expiry_u64_be || fee_u64_be ||
    orchard_v5_bundle_commitment_32
)
```

Orchard commitment 必须由上游库从实际 bundle 计算，不能信任交易对手声称的 32 字节值。所有花费授权签名和 binding signature 都对这个摘要签名。过期高度为零拒绝；fee 必须不大于 i64::MAX，且与 bundle 的 value balance 一致。接受的 bundle 版本和 flags 仍只有已固定的 V2 默认组合。

Go 的 DigestForCommitment 只提供可跨语言核对的摘要计算，不计算 Orchard commitment，也不验证零知识证明。真正授权检查由 Rust 固定验证密钥执行。标准库 SHA-256 和上游签名/证明实现不变，但这个新组合摘要仍属于待独立审查的 Zevune 协议设计，不宣称是 ZIP 244 的兼容实现。

## 4. 交易字节

```text
ASCII("ZVTXB001") || domain_id_32 || legacy_body_serialization
```

仅复用 `wire.rs` 定义的有界 BODY 字节布局，**不复用旧签名算法**。前缀增加 40 字节。body 固定 flags、2..8 个动作、规范的上游字段/曲线点、与动作数对应的证明长度及所有作者化字节。总长度不超过 40 + legacy MAX_ENVELOPE_SIZE，截断、多余尾部和未知 magic 一律拒绝。

旧签名外面加新前缀仍无效；从新交易剥掉前缀后，旧验证器也不能验证其签名。两个入口没有自动探测后重试、降级接受或共用授权缓存。精确 payload_digest=SHA256(整笔交易字节)，只是作者化数据标识，不是最终的 effects-only 主网交易 ID。

## 5. 验证结果的权限边界

新 `domain::Verifier` 与 `zevune-domain-check` 仅检查完整编码、独立预期域、全部花费签名、binding signature 和真实证明。它们**不检查**当前高度、已提交资产树根、已花费 nullifier、区块原子提交或网络最终确认。

成功回执明确为 `authorization_verified:true`、`ledger_checked:false`、`confirmed:false`、`real_funds_allowed:false`。任何生产节点均不能仅凭该回执入账。验证失败不会尝试旧格式验证，不写账本，不转移真实资金。

命令只接收公开描述符和公开交易字节，经 stdin 输入一笔有界交易；不接收钱包种子、花费私钥、查看密钥或明文支付见证。其故障输出不回显交易内容。

## 6. 验证与激活门槛

共享 `testdata/domain-v1.txt` 的六行固定向量，由独立 Python hashlib/整数编码生成，Go 与 Rust 均核对域原文、域 ID 和签名摘要。真实密码学测试检查不同类别/创世/规则/纪元、直接换域、改前缀、旧交易包裹、新交易剥壳、费用同步篡改、证明/签名/密文修改。跨语言测试让 Go 还原字节并启动真实 Rust 检查程序，缺少程序或语料会失败而非跳过。

现有程序不会因为该模块被合入而自动升级。下一步须将预期域从引导配置一路绑定到钱包签名、状态 worker 握手、日志头、共识应用和历史恢复；同时验证错误域交易不改变磁盘或内存状态。还须补齐完整资产守恒、发行、费用、版本升级及公网威胁模型，完成独立审查。未达到这些门槛，不对外宣称已有多节点跨网络重放防护或可以投入真实资产。

## 7. 设计参考

- ZIP 244，Transaction Identifier Non-Malleability：区分交易效果、作者化数据与签名摘要，绑定 consensus branch；本候选不是其完整兼容交易格式。https://zips.z.cash/zip-0244
- 上游锁定 Orchard 0.15.5 的 bundle commitment、apply_signatures、逐项签名与 verify_proof 实现，以 Cargo.lock 固定依赖为准。https://github.com/zcash/orchard

这些资料提供设计依据，不构成对 Zevune 集成代码的背书或审计。
