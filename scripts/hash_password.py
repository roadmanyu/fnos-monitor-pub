#!/usr/bin/env python3
"""生成 bcrypt 密码哈希，写入 config 的 auth.password_hash。"""
import sys
from getpass import getpass

from passlib.context import CryptContext

ctx = CryptContext(schemes=["bcrypt"], deprecated="auto")


def main():
    if len(sys.argv) > 1:
        pw = sys.argv[1]
    else:
        pw = getpass("Password: ")
    print(ctx.hash(pw))


if __name__ == "__main__":
    main()
