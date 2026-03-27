import os
import boto3
#import logging
from botocore.exceptions import ClientError
from dotenv import load_dotenv
from slack_bolt import App
from slack_sdk.errors import SlackApiError

#logging.basicConfig(level=logging.DEBUG)
#load_dotenv()

SLACK_SIGNING_SECRET = "EDR_SIGNING_SECRET_A09A7PN57N0"
SLACK_BOT_TOKEN = "EDR_BOT_TOKEN_A09A7PN57N0"
SLACK_USER_TOKEN = "EDR_USER_TOKEN_A09A7PN57N0"

region_name = "us-west-2"
# Create a Secrets Manager client
session = boto3.session.Session()
client = session.client(
    service_name='secretsmanager',
    region_name=region_name
)

def get_bot_token():
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=SLACK_BOT_TOKEN
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e
    secret = get_secret_value_response['SecretString']
    return secret

def get_signing_secret():
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=SLACK_SIGNING_SECRET
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    secret = get_secret_value_response['SecretString']
    return secret

def get_user_token():
    try:
        get_secret_value_response = client.get_secret_value(
            SecretId=SLACK_USER_TOKEN
        )
    except ClientError as e:
        # For a list of exceptions thrown, see
        # https://docs.aws.amazon.com/secretsmanager/latest/apireference/API_GetSecretValue.html
        raise e

    secret = get_secret_value_response['SecretString']
    return secret

def key_not_to_key():
    EDR_SIGNING_SECRET = get_signing_secret()
    EDR_BOT_TOKEN = get_bot_token()
    EDR_USER_TOKEN = get_user_token()

    if type(eval(EDR_SIGNING_SECRET)) is not str:
        if eval(EDR_SIGNING_SECRET) == dict:
            app = App(
                token=EDR_BOT_TOKEN[SLACK_BOT_TOKEN],
                signing_secret=EDR_SIGNING_SECRET[SLACK_SIGNING_SECRET]
            )
            app.client.api_test()
        else:
            print("EDR_SIGNING_SECRET is not a valid type. Expected dict or str.")
            print(f"Values: [{EDR_SIGNING_SECRET},\n{EDR_BOT_TOKEN},\n{EDR_USER_TOKEN}]")
            print("Please check your environment variables or secrets manager configuration.")
    elif eval(EDR_SIGNING_SECRET) == str:
        app = App(
            token=EDR_BOT_TOKEN,
            signing_secret=EDR_SIGNING_SECRET
        )
        app.client.api_test()
