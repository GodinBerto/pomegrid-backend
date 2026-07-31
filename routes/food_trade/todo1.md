# Todo
-Create a new registration signup for the food-trade app. It should use the genral user table then after the food-trade extended table then set the user role to "user" when ever a user registers through this endpoint.
-The registration should have the following fields for the user to fill. i want the registration to use this only and dont use any other tfield:
    - full_name (string)
    - email (string)
    - password (string)
    - phone (string)
    - region (string)
    - address (string)
- As for the login will use the gereal loggin.
- Create a new table for the weekly products. this will be used to display the weekly products in the home page. it should have the following fields:
    - name (string)
    - description (string)
    - price (float)
    - image_url (string)
    - status (string) with the following options 'active', 'inactive'. and by default it should be 'inactive' and the user should be able to update it.

## Product
- Create this additional endpoint for the products. its "/api/v1/food_trade/weekly_products" and it should return the products that have the weekly_product_status as 'active'
- Create an endpoint for getting the weekly product by id.
- Create an endpoint for updating, and deleting the weekly product. this endpoint is only for the admin.

## Work on the payment
- Use my payment method and create an endpoint for verifying if the paystack payment was successfull.
