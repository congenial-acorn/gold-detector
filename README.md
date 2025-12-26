# Gold Detector Discord Bot
## An Elite: Dangerous 3rd party tool
Bot invite link (also please read Bot Setup section): https://discord.com/oauth2/authorize?client_id=1415805825364267151

Please report all bugs by creating issues!

## Info
Trading is one of the best ways to make money in Elite: Dangerous, and the best way to trade is to buy low and sell high. Easy, right? Many factors affect market prices, but the Background Simulation (BGS) is among the most important.

The infrastructure failure BGS state causes the market price of gold to plunge by 90%, letting you trade gold for around 63k/ton profit. But if you go to Inara and look for these stations in infrastructure failure, you will see that all the stations are out of stock. Because Inara will list them as the top trade route by profit, they will get swarmed like locusts to a crop and suck up all the stock.

But some stations are hidden from Inara. The bubble is so large that not all stations are updated in real time. This bot will detect the stations that are in infrastructure failure, but without an updated market. So they will have ample stocks of gold for you to profit.

In addition, you can use this cheap gold to earn merits by selling it in accqusition system. The bot will alert you when such opportunities are available. You can choose which powerplay factions to recieve alerts from using commands. See [Preferences](#preferences) and [Commands](#commands). 

Note: You may read about other effects of BGS on markets here https://cdb.sotl.org.uk/effects

## Bot Setup (users)
Invite the bot using this link https://discord.com/oauth2/authorize?client_id=1415805825364267151 and select "Add to my apps".

IMPORTANT! Go to any channel and type `/alerts_on`. Or, click the 4-shapes icon on the right of any message input. Select the Market Finder app (gold bars profile picture, you may have to search for "Market Finder") and opt into messages using `/alerts_on`. To turn alerts off, use `/alerts_off`.

## Bot Setup (servers)
Invite the bot using this link https://discord.com/oauth2/authorize?client_id=1415805825364267151 and select a server.
Set a channel using `/set_alert_channel`. If you wish, create a role and set it using `/set_alert_role` to get pings.

If you don't do this, the bot will send to `#market-watch` and ping `@Market Alert` by default.

Alerts are sent by default. To disable alerts, use `/server_alerts_off`. To enable, use `/server_alerts_on`

Need to quiet ping mentions but keep the alerts flowing? Use `/server_ping_off` to suppress pings and `/server_ping_on` to turn them back on later.

## Preferences
Want to filter your alerts? Use `/set_preferences` to choose station types (Starport/Outpost/Surface Port), commodities (Gold/Palladium), or Powerplay leaders to include. Without setting preferences, you will receive all alerts by default.

## Commands
`/alerts_on`: Command to subscribe to DM alerts.

`/alerts_off`: Command to unsubscribe from DM alerts.

`/ping`: Check if bot is alive.

`/help`: Get a link to this page.

The following commands require Manage Guild permission and are for servers only.

`/server_alerts_off`: Server command to disable alerts.

`/server_alerts_on`: Server command to enable alerts. Note: Alerts are sent by default.

`/set_alert_channel`: Server command to set a custom channel. If not set, defaults to #market-watch.

`/clear_alert_channel`: Server command to revert to default channel (#market-watch).

`/set_alert_role`: Server command to set a custom role to ping. If not set, defaults to @Market Alert.

`/clear_alert_role`: Server command to revert to pinging the default role (@Market Alert).

`/server_ping_off`: Server command to stop sending @role pings while keeping alerts enabled.

`/server_ping_on`: Server command to resume @role pings.

`/show_alert_settings`: See the server's configuration.

These commands are for setting your preferences. Server preferences require Manage Guild permissions.

`/set_preferences station_type`: Choose allowed station types (Starport, Outpost, Surface Port). Add `target=server` to set server defaults (Manage Guild required); omit to set your personal DM/server filters.

`/set_preferences commodity`: Choose commodities to include (Gold, Palladium). Same `target` rules as above.

`/set_preferences powerplay`: Choose Powerplay leaders you care about. Non-selected leaders are muted. Same `target` rules as above.

`/set_preferences show`: Display current preferences for you or the server.

`/set_preferences remove`: Remove specific options from a category.

`/set_preferences clear`: Clear one category or all preferences.

## Usage
After setting up the bot, simply wait for pings. Successful gold detections will occur sometimes a few times a week, sometimes once a month. Alerts have a cooldown of 48 hours. Sometimes, some fields of the message will be "unknown". These stations are still worth visiting because sometimes Inara does not get full market data due to colonization.

Once you get a message, just go to the station in your hauling ship (and your carrier if you have one) and then start buying the gold. You can use Inara commodity search to find good gold sell prices nearby. Or you can load your carrier to the top and then find good sell prices later. You can make hundreds of millions of credits by doing this, and this is definitely the best trading you can find outside of much rarer special conditions.

Note: when you get to the station, you will see the stock is 10% of what the bot reports. The stock will actually refill over time until all of the stock it originally had is gone so do not worry.

### Legal

The source code is now under the MIT license since v1.5.0 (previously under CC0). 

Neither the bot nor the developer is associated with Frontier Developments, Elite Dangerous, Inara.cz, or any other member or tool of the Elite Dangerous community.
