@echo off
rem 生成 release 签名密钥（仅首次需要；已有 lcm-release.keystore 时勿重复生成，
rem 否则升级包签名不一致无法覆盖安装）。
rem 交互式填写密码与姓名/组织信息，完成后按 README 提示填写 app/keystore.properties。
keytool -genkeypair -v -keystore "%~dp0..\app\lcm-release.keystore" -alias lcm ^
  -keyalg RSA -keysize 2048 -validity 10950 -storetype PKCS12
