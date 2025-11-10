## STATUS
Version 1.2.3 has been deployed. Last updated: 11/10, 12:00 AM UTC.

Read the changelog [here](https://github.com/congenial-acorn/gold-detector/blob/main/CHANGELOG.md). Scroll down for bot info.

# Gold Detector Discord Bot
## An Elite: Dangerous 3rd party tool
Bot invite link (also please read Bot Setup section): https://discord.com/oauth2/authorize?client_id=1415805825364267151

Please report all bugs by creating issues!

## Bot Setup (users)
Invite the bot using this link https://discord.com/oauth2/authorize?client_id=1415805825364267151 and select "Add to my apps".

IMPORTANT! Opt into messages using `/alerts_on`. To turn alerts off, use `/alerts_off`.

## Bot Setup (servers)
Invite the bot using this link https://discord.com/oauth2/authorize?client_id=1415805825364267151 and select a server.
Set a channel using `/set_alert_channel`. If you wish, create a role and set it using `/set_alert_role` to get pings.

If you don't do this, the bot will send to `#market-watch` and ping `@Market Alert` by default.

Alerts are sent by default. To disable alerts, use `/server_alerts_off`. To enable, use `/server_alerts_on`

## Commands
`/alerts_on`: Command to subscribe to DM alerts.

`/alerts_off`: Command to unsubscribe from DM alerts.

`/ping`: Check if bot is alive.

`/help`: Get a link to this page.

The following commands require Manage Guild permission.

`/server_alerts_off`: Server command to disable alerts.

`/server_alerts_on`: Server command to enable alerts. Note: Alerts are sent by default.

`/set_alert_channel`: Server command to set a custom channel. If not set, defaults to #market-watch.

`/clear_alert_channel`: Server command to revert to default channel (#market-watch).

`/set_alert_role`: Server command to set a custom role to ping. If not set, defaults to @Market Alert.

`/clear_alert_role`: Server command to revert to pinging the default role (@Market Alert).

`/show_alert_settings`: See the server's configuration.

## Info
Infrastructure failure is a well-known BGS state. You are probably aware of its effects on gold prices from CMDR Mechan's merit farming video https://youtu.be/Ju1t9RlfnVQ.
Of course, with the merit farming method, you don't make any money because you are buying gold at full price.

But what if you could buy the gold truly at that 90% discount of infrastructure failure? You could make 63k profit/ton at ideal conditions.
Now, if you go to Inara and look for these stations in infrastructure failure, you will see that all the stations are out of stock. Because Inara will list them as the top trade route by profit, and they will get swarmed like a swarm of locusts and suck up all the stock.

But there are stations that are hidden from Inara. Because the site depends on user data, and the bubble is so huge that not all stations are updated all the time.
This bot will detect the stations that are in infrastructure failure, but without an updated market. So they will have ample stocks of gold for you to profit.

Note: You may read about other effects of BGS on markets here https://cdb.sotl.org.uk/effects

## Usage
After setting up the bot, simply wait for pings. Successful gold detections will occur sometimes a few times a week, sometimes once a month. Alerts have a cooldown of 48 hours. Sometimes, some fields of the message will be "unknown". These stations are still worth visiting because sometimes Inara does not get full market data due to colonization.

Once you get a message, just go to the station in your hauling ship (and your carrier if you have one) and then start buying the gold. You can use Inara commodity search to find good gold sell prices nearby. Or you can load your carrier to the top and then find good sell prices later. You can make hundreds of millions of credits by doing this, and this is definitely the best trading you can find outside of much rarer special conditions. 

Note: when you get to the station, you will see the stock is much lower than the bot reported. The stock will actually refill over time until all of the stock it originally had is gone so do not worry.

### Legal
The source code is released under CC0. Neither the bot nor the developer is associated with Frontier Developments, Elite Dangerous, Inara.cz, or any other member or tool of the Elite Dangerous community.
